package preflight

import (
	"regexp"
	"slices"
	"sort"
	"strings"
)

type scope struct {
	options map[string][]string
	formats map[string][]string
}

func newScope() *scope {
	return &scope{options: map[string][]string{}, formats: map[string][]string{}}
}

type frame struct {
	nodes   []*node
	index   int
	depth   int
	inHTTP  bool
	scope   *scope
	file    string
	entered bool
}

// ValidateNginx checks the complete successful nginx -T stdout, including every
// file section and include context. It never opens included files itself.
func ValidateNginx(data []byte) error {
	source, err := text(data)
	if err != nil {
		return err
	}
	first, files, err := dumpFiles(source)
	if err != nil {
		return err
	}
	trees := map[string][]*node{}
	parts := map[string][]string{}
	var paths []string
	for name, body := range files {
		trees[name], err = parseNginx(body)
		if err != nil {
			return err
		}
		parts[name] = strings.Split(name, "/")
		paths = append(paths, name)
	}
	sort.Strings(paths)
	main := newScope()
	var httpScopes []*scope
	seen, active := map[string]bool{}, map[string]bool{}
	globs := map[string][]*regexp.Regexp{}
	stack := []frame{{nodes: trees[first], scope: main, file: first}}
	budget := 100000
	for len(stack) > 0 {
		f := &stack[len(stack)-1]
		if f.file != "" && !f.entered {
			if active[f.file] {
				return ErrConfig
			}
			seen[f.file], active[f.file], f.entered = true, true, true
		}
		if f.index == len(f.nodes) {
			if f.file != "" {
				delete(active, f.file)
			}
			stack = stack[:len(stack)-1]
			continue
		}
		budget--
		if budget < 0 {
			return ErrConfig
		}
		item := f.nodes[f.index]
		f.index++
		name, args := item.words[0], item.words[1:]
		if name == "include" {
			if item.block || len(args) != 1 || strings.Contains(args[0], "$") {
				return ErrConfig
			}
			pattern := args[0]
			if !strings.HasPrefix(pattern, "/") {
				pattern = first[:strings.LastIndex(first, "/")+1] + pattern
			}
			pattern = cleanPath(pattern)
			compiled, found := globs[pattern]
			if !found {
				for _, part := range strings.Split(pattern, "/") {
					glob, err := componentGlob(part)
					if err != nil {
						return err
					}
					compiled = append(compiled, glob)
				}
				globs[pattern] = compiled
			}
			var matches []string
			for _, path := range paths {
				if len(parts[path]) != len(compiled) {
					continue
				}
				match := true
				for i, part := range parts[path] {
					if !compiled[i].MatchString(part) {
						match = false
						break
					}
				}
				if match {
					matches = append(matches, path)
				}
			}
			if len(matches) == 0 && !strings.ContainsAny(pattern, "*?[") {
				return ErrConfig
			}
			parent := *f
			for i := len(matches) - 1; i >= 0; i-- {
				path := matches[i]
				stack = append(stack, frame{nodes: trees[path], depth: parent.depth,
					inHTTP: parent.inHTTP, scope: parent.scope, file: path})
			}
			continue
		}
		if err := validateDirective(item, *f); err != nil {
			return err
		}
		if item.block {
			childScope := newScope()
			if name == "http" {
				if f.depth != 0 || len(args) != 0 {
					return ErrConfig
				}
				httpScopes = append(httpScopes, childScope)
			}
			stack = append(stack, frame{nodes: item.children, depth: f.depth + 1,
				inHTTP: f.inHTTP || f.depth == 0 && name == "http", scope: childScope})
		}
	}
	if len(seen) != len(trees) || main.options["error_log"] == nil || !slices.Equal(main.options["worker_shutdown_timeout"], []string{"2s"}) || len(httpScopes) != 1 {
		return ErrConfig
	}
	if !slices.Equal(httpScopes[0].options["access_log"], []string{"/dev/stdout", "privacy_counts"}) || !slices.Equal(httpScopes[0].formats["privacy_counts"], []string{NginxFormat}) {
		return ErrConfig
	}
	return nil
}

func validateDirective(item *node, f frame) error {
	name, args := item.words[0], item.words[1:]
	switch name {
	case "access_log", "error_log", "worker_shutdown_timeout", "master_process", "daemon":
		if _, duplicate := f.scope.options[name]; duplicate || item.block {
			return ErrConfig
		}
		f.scope.options[name] = args
		switch name {
		case "access_log":
			if !f.inHTTP || !(slices.Equal(args, []string{"off"}) || slices.Equal(args, []string{"/dev/stdout", "privacy_counts"})) {
				return ErrConfig
			}
		case "error_log":
			if !(slices.Equal(args, []string{"stderr"}) || len(args) == 2 && args[0] == "stderr" && slices.Contains([]string{"debug", "info", "notice", "warn", "error", "crit", "alert", "emerg"}, args[1])) {
				return ErrConfig
			}
		case "worker_shutdown_timeout":
			if f.depth != 0 || !slices.Equal(args, []string{"2s"}) {
				return ErrConfig
			}
		case "master_process":
			if f.depth != 0 || !slices.Equal(args, []string{"on"}) {
				return ErrConfig
			}
		case "daemon":
			if f.depth != 0 || !slices.Equal(args, []string{"off"}) {
				return ErrConfig
			}
		}
	case "log_format":
		if item.block || len(args) < 2 || !f.inHTTP || f.depth != 1 {
			return ErrConfig
		}
		if _, duplicate := f.scope.formats[args[0]]; duplicate {
			return ErrConfig
		}
		f.scope.formats[args[0]] = args[1:]
		if args[0] == "privacy_counts" && !slices.Equal(args, []string{"privacy_counts", NginxFormat}) {
			return ErrConfig
		}
	}
	return nil
}

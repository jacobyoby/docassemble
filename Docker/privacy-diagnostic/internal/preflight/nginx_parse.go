package preflight

import (
	"path"
	"regexp"
	"strings"
)

var header = regexp.MustCompile(`^# configuration file (/[^\r\n]+):\r?\n?$`)

func cleanPath(value string) string {
	clean := path.Clean(value)
	// POSIX preserves exactly two leading slashes; the frozen parser does too.
	if strings.HasPrefix(value, "//") && !strings.HasPrefix(value, "///") {
		if clean == "/" {
			return "//"
		}
		return "/" + clean
	}
	return clean
}

func dumpFiles(source string) (string, map[string]string, error) {
	files := map[string]string{}
	first, current := "", ""
	var body strings.Builder
	var quote rune
	active, escaped := false, false
	finish := func() bool {
		if current != "" {
			content := body.String()
			if previous, found := files[current]; found && previous != content {
				return false
			}
			files[current] = content
		}
		return true
	}
	for _, line := range lines(source) {
		if quote == 0 && !active && !escaped {
			if match := header.FindStringSubmatch(line); match != nil {
				if !finish() || cleanPath(match[1]) != match[1] {
					return "", nil, ErrConfig
				}
				current = match[1]
				if first == "" {
					first = current
				}
				body.Reset()
				continue
			}
		}
		if current == "" && strings.TrimSpace(line) != "" {
			return "", nil, ErrConfig
		}
		body.WriteString(line)
		for _, char := range line {
			if escaped {
				escaped = false
				continue
			}
			if char == '\\' {
				escaped, active = true, true
			} else if quote != 0 {
				if char == quote {
					quote = 0
				}
			} else if char == '#' && !active {
				break
			} else if !active && (char == '"' || char == '\'') {
				quote, active = char, true
			} else if space(char) || strings.ContainsRune(";{}", char) {
				active = false
			} else {
				active = true
			}
		}
	}
	if quote != 0 || escaped || first == "" || !finish() {
		return "", nil, ErrConfig
	}
	return first, files, nil
}

type token struct {
	kind rune // zero for a word; otherwise a native delimiter
	word string
}

func tokens(source string) ([]token, error) {
	var result []token
	var word strings.Builder
	active, afterQuote := false, false
	var quote rune
	chars := []rune(source)
	flush := func() {
		result = append(result, token{word: word.String()})
		word.Reset()
		active = false
	}
	for i := 0; i < len(chars); i++ {
		char := chars[i]
		if afterQuote {
			if !space(char) && !strings.ContainsRune(";{})", char) {
				return nil, ErrConfig
			}
			if char == ')' {
				flush()
			}
			afterQuote = false
		}
		switch {
		case char == '\\':
			if i+1 == len(chars) {
				return nil, ErrConfig
			}
			i++
			// ngx_conf_read_token: only these escapes are decoded. Unknown
			// escapes retain the backslash, including regex \., \b and \?.
			switch chars[i] {
			case 't':
				word.WriteRune('\t')
			case 'r':
				word.WriteRune('\r')
			case 'n':
				word.WriteRune('\n')
			case '\\', '"', '\'':
				word.WriteRune(chars[i])
			default:
				word.WriteRune('\\')
				word.WriteRune(chars[i])
			}
			active = true
		case quote != 0:
			if char == quote {
				quote, afterQuote = 0, true
			} else {
				word.WriteRune(char)
			}
		case char == '#' && !active:
			for i < len(chars) && chars[i] != '\n' {
				i++
			}
		case char == '"' || char == '\'':
			if active {
				return nil, ErrConfig
			}
			quote, active = char, true
		case char == '$' && i+1 < len(chars) && chars[i+1] == '{':
			end := i + 2
			for end < len(chars) && chars[end] != '}' {
				r := chars[end]
				if !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '_') {
					return nil, ErrConfig
				}
				end++
			}
			if end >= len(chars) || end == i+2 {
				return nil, ErrConfig
			}
			word.WriteString(string(chars[i : end+1]))
			active, i = true, end
		case space(char) || strings.ContainsRune(";{}", char):
			if active {
				flush()
			}
			if strings.ContainsRune(";{}", char) {
				result = append(result, token{kind: char})
			}
		default:
			word.WriteRune(char)
			active = true
		}
		if len(result) > 100000 {
			return nil, ErrConfig
		}
	}
	if quote != 0 {
		return nil, ErrConfig
	}
	if active {
		flush()
	}
	if len(result) > 100000 {
		return nil, ErrConfig
	}
	return result, nil
}

type node struct {
	words    []string
	children []*node
	block    bool
}

func parseNginx(source string) ([]*node, error) {
	input, err := tokens(source)
	if err != nil {
		return nil, err
	}
	root := &node{block: true}
	stack := []*node{root}
	var words []string
	for _, item := range input {
		switch item.kind {
		case 0:
			words = append(words, item.word)
		case ';', '{':
			if len(words) == 0 || words[0] == "" {
				return nil, ErrConfig
			}
			child := &node{words: words, block: item.kind == '{'}
			parent := stack[len(stack)-1]
			parent.children = append(parent.children, child)
			words = nil
			if child.block {
				stack = append(stack, child)
				if len(stack) > 64 {
					return nil, ErrConfig
				}
			}
		case '}':
			if len(words) != 0 || len(stack) <= 1 {
				return nil, ErrConfig
			}
			stack = stack[:len(stack)-1]
		}
	}
	if len(words) != 0 || len(stack) != 1 {
		return nil, ErrConfig
	}
	return root.children, nil
}

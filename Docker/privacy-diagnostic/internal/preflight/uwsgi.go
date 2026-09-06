package preflight

import (
	"strconv"
	"strings"
)

// ValidateUwsgi accepts only the options used by the four owned templates.
func ValidateUwsgi(data []byte) error {
	source, err := text(data)
	if err != nil || strings.Contains(source, "{{") || strings.Contains(source, "}}") {
		return ErrConfig
	}
	options := map[string]string{}
	section := false
	for _, raw := range lines(source) {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, ";") {
			continue
		}
		if strings.HasPrefix(line, "[") {
			if section || line != "[uwsgi]" {
				return ErrConfig
			}
			section = true
			continue
		}
		key, value, found := strings.Cut(line, "=")
		key, value = strings.TrimSpace(key), strings.TrimSpace(value)
		if !section || !found || value == "" || options[key] != "" || !uwsgiOption(key, value) {
			return ErrConfig
		}
		options[key] = value
	}
	if !section || options["master"] != "true" || options["die-on-term"] != "true" || options["log-format"] != UwsgiFormat {
		return ErrConfig
	}
	return nil
}

func uwsgiOption(key, value string) bool {
	switch key {
	case "master", "enable-threads", "vhost", "manage-script-name", "die-on-term":
		return value == "true"
	case "socket", "venv", "pidfile", "touch-reload", "py-executable":
		return absolute(value)
	case "processes", "threads", "buffer-size", "max-fd":
		if len(value) == 0 || len(value) > 7 || value[0] < '1' || value[0] > '9' {
			return false
		}
		for _, digit := range value {
			if digit < '0' || digit > '9' {
				return false
			}
		}
		n, err := strconv.Atoi(value)
		return err == nil && n <= 1048576
	case "mount":
		prefix, target, found := strings.Cut(value, "=")
		return found && (prefix == "/" || absolute(prefix)) && target == "docassemble.webapp.run:application"
	case "module":
		return value == "docassemble.webapp.listlog"
	case "callable":
		return value == "app"
	case "http-socket":
		return value == ":80"
	case "log-format":
		return value == UwsgiFormat
	default:
		return false
	}
}

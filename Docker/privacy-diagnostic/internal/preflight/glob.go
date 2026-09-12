package preflight

import (
	"fmt"
	"regexp"
	"strings"
)

// Compile one path component with fnmatch-style *, ?, ranges, and ! negation.
// Regex uses linear-time RE2; matching components separately prevents a glob
// from crossing directory boundaries. Unclosed brackets are literal text.
func componentGlob(pattern string) (*regexp.Regexp, error) {
	chars := []rune(pattern)
	var expression strings.Builder
	expression.WriteString("(?s)^(")
	for i := 0; i < len(chars); i++ {
		switch chars[i] {
		case '*':
			expression.WriteString(".*")
			for i+1 < len(chars) && chars[i+1] == '*' {
				i++
			}
		case '?':
			expression.WriteByte('.')
		case '[':
			start := i + 1
			end := start
			if end < len(chars) && chars[end] == '!' {
				end++
			}
			if end < len(chars) && chars[end] == ']' {
				end++
			}
			for end < len(chars) && chars[end] != ']' {
				end++
			}
			if end == len(chars) {
				expression.WriteString(`\[`)
				continue
			}
			expression.WriteString(globClass(chars[start:end]))
			i = end
		default:
			expression.WriteString(regexp.QuoteMeta(string(chars[i])))
		}
	}
	expression.WriteString(")$")
	compiled, err := regexp.Compile(expression.String())
	if err != nil {
		return nil, ErrConfig
	}
	return compiled, nil
}

type classPart struct {
	char      rune
	connector bool
}

func globClass(chars []rune) string {
	// Match Python fnmatch's empty-range normalization before interpreting !.
	// Removing a descending range can expose a leading ! (for example []-!![]).
	var chunks [][]rune
	start, search := 0, 1
	if chars[0] == '!' {
		search++
	}
	for search < len(chars) {
		if chars[search] != '-' {
			search++
			continue
		}
		chunks = append(chunks, append([]rune(nil), chars[start:search]...))
		start, search = search+1, search+3
	}
	if start < len(chars) {
		chunks = append(chunks, append([]rune(nil), chars[start:]...))
	} else {
		chunks[len(chunks)-1] = append(chunks[len(chunks)-1], '-')
	}
	for i := len(chunks) - 1; i > 0; i-- {
		left, right := chunks[i-1], chunks[i]
		if left[len(left)-1] > right[0] {
			chunks[i-1] = append(left[:len(left)-1], right[1:]...)
			chunks = append(chunks[:i], chunks[i+1:]...)
		}
	}
	var parts []classPart
	for i, chunk := range chunks {
		if i > 0 {
			parts = append(parts, classPart{char: '-', connector: true})
		}
		for _, char := range chunk {
			parts = append(parts, classPart{char: char})
		}
	}
	if len(parts) == 0 {
		return "a^" // Empty range cannot match.
	}
	negative := parts[0].char == '!'
	if negative {
		parts = parts[1:]
		if len(parts) == 0 {
			return "."
		}
	}
	var expression strings.Builder
	expression.WriteByte('[')
	if negative {
		expression.WriteByte('^')
	}
	for i := 0; i < len(parts); i++ {
		low, high := parts[i].char, parts[i].char
		if !parts[i].connector && i+2 < len(parts) && parts[i+1].connector && !parts[i+2].connector {
			high = parts[i+2].char
			i += 2
		}
		fmt.Fprintf(&expression, `\x{%x}-\x{%x}`, low, high)
	}
	expression.WriteByte(']')
	return expression.String()
}

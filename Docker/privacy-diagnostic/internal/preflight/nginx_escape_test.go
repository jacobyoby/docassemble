package preflight

import (
	"reflect"
	"strings"
	"testing"
)

func TestNginxEscapeTokens(t *testing.T) {
	// Nginx 1.28.3 ngx_conf_read_token decodes a small escape set in both
	// quoted and unquoted tokens. Regex and delimiter escapes retain the slash.
	for _, test := range []struct{ source, want string }{
		{`"line\n\t\rend"`, "line\n\t\rend"},
		{`'line\n\t\rend'`, "line\n\t\rend"},
		{`line\n\t\rend`, "line\n\t\rend"},
		{`"quote\" and \' and \\"`, `quote" and ' and \`},
		{`'quote\' and \" and \\'`, `quote' and " and \`},
		{`"\?\b\."`, `\?\b\.`},
		{`\.`, `\.`},
		{`a\;b\{c\}d\#e\ f`, `a\;b\{c\}d\#e\ f`},
		{`"a\\\"b"`, `a\"b`},
		{`"a\\"`, `a\`},
		{"a\\\nb", "a\\\nb"},
	} {
		got, err := tokens(test.source + ";")
		want := []token{{word: test.want}, {kind: ';'}}
		if err != nil || !reflect.DeepEqual(got, want) {
			t.Errorf("tokens(%q) = %#v, %v; want %#v", test.source, got, err, want)
		}
	}
}

func TestNginxEscapesDoNotHideDumpBoundariesOrUnsafeLogs(t *testing.T) {
	for _, data := range []string{
		`"regex\?\b\. and newline\n"`,
		"\"escaped\\\"\n# configuration file /fake:\nend\"",
		`'escaped\' and \\ end'`,
	} {
		body := strings.Replace(minimalNginx, httpBase, httpBase+" server { set $data "+data+"; }", 1)
		if err := ValidateNginx(singleDump(body)); err != nil {
			t.Errorf("valid escaped data rejected: %q", data)
		}
	}
	// An unquoted continuation is a lexical boundary control, not a valid
	// `set` directive: the spaces in this fake header create extra arguments.
	continued := string(singleDump(minimalNginx + "\nword\\\n# configuration file /fake:\nend;"))
	if _, files, err := dumpFiles(continued); err != nil || len(files) != 1 {
		t.Fatal("continued word split a fake dump header")
	}
	comment := singleDump(minimalNginx + "\n# ignored slash \\\n")
	if ValidateNginx(comment) != nil {
		t.Fatal("comment escape changed parser state")
	}
	for _, directive := range []string{
		`access_log o\ff;`, `access_log "o\ff";`,
		`access_log /tmp/private\;log privacy_counts;`,
		`error_log "std\nerr";`,
		`include /etc/nginx/\*.conf;`,
		`set $data "dangling\`, `set $data dangling\`,
		`set $data "unterminated\";`,
	} {
		body := strings.Replace(minimalNginx, httpBase, httpBase+" server { "+directive+" }", 1)
		if ValidateNginx(singleDump(body)) == nil {
			t.Errorf("unsafe or incomplete directive accepted: %q", directive)
		}
	}
	for _, bad := range []string{`word\`, `"word\`, `"word\"`} {
		if _, err := tokens(bad); err == nil {
			t.Errorf("incomplete token accepted: %q", bad)
		}
	}
}

# Preserve the application import boundary without installing a file logger.
# The existing docassemble.base.logger callback writes to stderr. Supported
# service launchers must route stdout/stderr through privacy-process; that Go
# process owns fixed counter output, delivery deadlines, and failure reporting.
# Do not install this package without the complete privacy service profile.
# See docs/privacy/application-logger-go.md in the maintained source checkout.

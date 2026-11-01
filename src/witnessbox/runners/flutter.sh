# Legacy compatibility only: new integrations should provide their own test.sh.
# Sourced by gate.sh after runner selection, never by the checker.
select_legacy_flutter() {
  runner_kind=flutter
  runner="flutter test --no-pub ${tests:-test/ebt}"
  runner_command=(flutter test --no-pub)
  [ -n "$tests" ] || runner_command+=(test/ebt)
}

legacy_flutter_environment() {
  local description
  description=$(flutter --version) || return 2
  runner_environment=${description%%$'\n'*}
}

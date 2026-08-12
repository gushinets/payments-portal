# METADATA
# title: Compose services must not share host namespaces
# description: Host network, PID, or IPC modes weaken container isolation.
# custom:
#   id: ANY-COMPOSE-002
#   severity: HIGH
#   input:
#     selector:
#       - type: yaml
package user.compose_no_host_namespaces

deny[res] {
    some service_name
    service := input.services[service_name]
    service.network_mode == "host"
    message := sprintf("Compose service %q must not use the host network namespace", [service_name])
    res := result.new(message, service.network_mode)
}

deny[res] {
    some service_name
    service := input.services[service_name]
    service.pid == "host"
    message := sprintf("Compose service %q must not use the host PID namespace", [service_name])
    res := result.new(message, service.pid)
}

deny[res] {
    some service_name
    service := input.services[service_name]
    service.ipc == "host"
    message := sprintf("Compose service %q must not use the host IPC namespace", [service_name])
    res := result.new(message, service.ipc)
}

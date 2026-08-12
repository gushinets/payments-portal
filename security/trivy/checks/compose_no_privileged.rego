# METADATA
# title: Compose services must not run privileged
# description: Privileged containers bypass most container isolation controls.
# custom:
#   id: ANY-COMPOSE-001
#   severity: CRITICAL
#   input:
#     selector:
#       - type: yaml
package user.compose_no_privileged

deny[res] {
    some service_name
    service := input.services[service_name]
    service.privileged == true
    message := sprintf("Compose service %q must not run privileged", [service_name])
    res := result.new(message, service.privileged)
}

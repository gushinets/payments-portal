# METADATA
# title: Compose services must not add every Linux capability
# description: Adding ALL capabilities removes an important container boundary.
# custom:
#   id: ANY-COMPOSE-004
#   severity: HIGH
#   input:
#     selector:
#       - type: yaml
package user.compose_no_all_capabilities

deny[res] {
    some service_name
    service := input.services[service_name]
    some capability_index
    capability := service.cap_add[capability_index]
    lower(capability) == "all"
    message := sprintf("Compose service %q must not add all Linux capabilities", [service_name])
    res := result.new(message, capability)
}

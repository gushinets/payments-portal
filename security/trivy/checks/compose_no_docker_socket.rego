# METADATA
# title: Compose services must not mount the Docker socket
# description: Docker socket access is equivalent to control of the container host.
# schemas:
#   - input: schema["docker-compose"]
# custom:
#   id: ANY-COMPOSE-003
#   severity: CRITICAL
#   input:
#     selector:
#       - type: yaml
package user.compose_no_docker_socket

deny[res] {
    some service_name
    service := input.services[service_name]
    some volume_index
    volume := service.volumes[volume_index]
    is_string(volume)
    startswith(volume, "/var/run/docker.sock:")
    message := sprintf("Compose service %q must not mount the Docker socket", [service_name])
    res := result.new(message, volume)
}

deny[res] {
    some service_name
    service := input.services[service_name]
    some volume_index
    volume := service.volumes[volume_index]
    is_object(volume)
    volume.type == "bind"
    volume.source == "/var/run/docker.sock"
    message := sprintf("Compose service %q must not mount the Docker socket", [service_name])
    res := result.new(message, volume)
}

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

is_docker_socket_source(source) {
    source == "/var/run/docker.sock"
}

is_docker_socket_source(source) {
    source == "/run/docker.sock"
}

deny[res] {
    some service_name
    service := input.services[service_name]
    some volume_index
    volume := service.volumes[volume_index]
    is_string(volume)
    parts := split(volume, ":")
    count(parts) >= 2
    is_docker_socket_source(parts[0])
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
    is_docker_socket_source(volume.source)
    message := sprintf("Compose service %q must not mount the Docker socket", [service_name])
    res := result.new(message, volume)
}

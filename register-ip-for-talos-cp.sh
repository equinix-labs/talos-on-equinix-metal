#!/usr/bin/env bash

IP_RESERVATIONS_FILE="secrets/ip-reservation.yaml"
IP_ADDRESSES_FILE="secrets/ip-addresses.yaml"
REQUESTED_IP_COUNT="1"

function request-ips {
  if [ -f "${IP_ADDRESSES_FILE}" ]; then
  	echo "You already have IPs in ${IP_ADDRESSES_FILE}"
  	return
	fi

	if [ ! -f ${IP_RESERVATIONS_FILE} ]; then
  	metal ip request -p "${METAL_PROJECT_ID}" -t public_ipv4 -q "${REQUESTED_IP_COUNT}" -f "${FACILITY}" --tags "talos-cp-vip,cluster:${CLUSTER_NAME}" -o yaml > "${IP_RESERVATIONS_FILE}"
  fi

  metal ip available -r "$(yq '.id' ${IP_RESERVATIONS_FILE})" -c 32 -o yaml > ${IP_ADDRESSES_FILE}
}

request-ips
export TOEM_CP_ENDPOINT="$(yq '.[0]' secrets/ip-addresses.yaml | cut -d "/" -f 1)"
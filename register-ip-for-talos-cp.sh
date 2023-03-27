#!/usr/bin/env bash

ALL_IPS_FILES="${TOEM_PROJECT_ROOT}/secrets/all-ips.yaml"

function request-ips {
	local addressRole="${1}"
	local requestedIPCount="${2}"
	local requestedIPScope="${3}"
	local ipReservationsFile="${TOEM_PROJECT_ROOT}/secrets/ip-${addressRole}-reservation.yaml"
  local ipAddressesFile="${TOEM_PROJECT_ROOT}/secrets/ip-${addressRole}-addresses.yaml"

  local cpEndpoint=$(addressRole="talos-${addressRole}-vip" clusterName="cluster:${CLUSTER_NAME}" yq '.[] | select(.facility.code == strenv(FACILITY)) | select(.tags[0] == env(addressRole) and .tags[1] == strenv(clusterName)) | .address' "${ALL_IPS_FILES}")
  echo $cpEndpoint
  if [ -z "${cpEndpoint}" ] || [ ! -f ${ipReservationsFile} ]; then
  	metal ip request -p "${METAL_PROJECT_ID}" -t "${requestedIPScope}" -q "${REQUESTED_IP_COUNT}" -f "${FACILITY}" --tags "talos-${addressRole}-vip,cluster:${CLUSTER_NAME}" -o yaml > "${ipReservationsFile}"
  	metal ip available -r "$(yq '.id' ${ipReservationsFile})" -c 32 -o yaml > ${ipAddressesFile}
	else
		echo "bla!"
	fi

}

#metal ip get -o yaml > "${ALL_IPS_FILES}" "public_ipv4"

#request-ips "cp" "1"
test="line1
line2
line3
line4
line5"

index=0
ipAddresses="[]"
while IFS= read -r address; do
	ipAddresses=$(echo "${ipAddresses}" | index="${index}" address="${address}" yq '.[env(index)] = env(address)')
	(( index++ ))
done <<< "${test}"

echo $ipAddresses



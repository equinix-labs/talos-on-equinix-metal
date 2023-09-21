List objects in a bucket 
```shell
radosgw-admin bucket list --rgw-realm [realm_name] --bucket [bucket_name]
```

We are using:
- https://docs.ceph.com/en/quincy/radosgw/multisite/ 

Workloads need to support s3 as storage backend
- https://jfrog.com/help/r/jfrog-installation-setup-documentation/s3-object-storage 
- https://goharbor.io/docs/2.2.0/install-config/configure-yml-file/#backend
  - https://docs.docker.com/registry/configuration/#storage
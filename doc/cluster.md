# apiserver enbled plugins
```shell
kubectl -n kube-system exec kube-apiserver-talos-alloy-102-control-plane-kccvj -it -- kube-apiserver -h | grep "default enabled ones"
  --enable-admission-plugins strings       admission plugins that should be enabled in addition to default enabled ones (
  NamespaceLifecycle, LimitRanger, ServiceAccount, TaintNodesByCondition, PodSecurity, Priority, 
  DefaultTolerationSeconds, DefaultStorageClass, StorageObjectInUseProtection, PersistentVolumeClaimResize, 
  RuntimeClass, CertificateApproval, CertificateSigning, CertificateSubjectRestriction, DefaultIngressClass, 
  MutatingAdmissionWebhook, ValidatingAdmissionPolicy, ValidatingAdmissionWebhook, ResourceQuota). 
  Comma-delimited list of admission plugins: AlwaysAdmit, AlwaysDeny, AlwaysPullImages, CertificateApproval, 
  CertificateSigning, CertificateSubjectRestriction, DefaultIngressClass, DefaultStorageClass, 
  DefaultTolerationSeconds, DenyServiceExternalIPs, EventRateLimit, ExtendedResourceToleration, 
  ImagePolicyWebhook, LimitPodHardAntiAffinityTopology, LimitRanger, MutatingAdmissionWebhook, 
  NamespaceAutoProvision, NamespaceExists, NamespaceLifecycle, NodeRestriction, 
  OwnerReferencesPermissionEnforcement, PersistentVolumeClaimResize, PersistentVolumeLabel, PodNodeSelector, 
  PodSecurity, PodTolerationRestriction, Priority, ResourceQuota, RuntimeClass, SecurityContextDeny, 
  ServiceAccount, StorageObjectInUseProtection, TaintNodesByCondition, ValidatingAdmissionPolicy, 
  ValidatingAdmissionWebhook. The order of plugins in this flag does not matter.
```
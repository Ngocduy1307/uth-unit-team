# uth-unit-team

helm repo add camunda https://helm.camunda.io
helm repo update

kubectl create namespace camunda
helm install affordability camunda/camunda-platform --version 14.2.0 -f camunda-values.yaml -n camunda

helm uninstall affordability -n camunda
kubectl delete pvc --all -n 
kubectl delete pvc --all -n camunda

kubectl port-forward svc/affordability-zeebe-gateway 8081:8080 26500:26500 -n camunda
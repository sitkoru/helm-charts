# dotnet-app

Chart развёртывает приложение с HTTP и gRPC Services. Оба gRPC
`ExternalAddress` получают IP конкретного Pod через Downward API `status.podIP`.
Services сохраняются для клиентов, обращающихся по их именам.

## DNS для Consul

| Параметр | По умолчанию | Назначение |
| --- | --- | --- |
| `consulDns.enabled` | `true` | Получать адрес DNS при установке и обновлении chart |
| `consulDns.serviceName` | `kube-dns-upstream` | Имя Service, ведущего к DNS с поддержкой зоны `.consul` |
| `consulDns.serviceNamespace` | `kube-system` | Пространство имён DNS Service |

При `consulDns.enabled=true` Helm читает указанный Service через `lookup` и
задаёт `ServiceDiscovery__Consul__DnsServers__0` значением `<clusterIP>:53`.
Service должен существовать и иметь непустой `spec.clusterIP`, отличный от
`None`; иначе рендеринг завершается понятной ошибкой. DNS должен обслуживать
запросы на порту 53. Chart не включает обнаружение сервисов: его включение и
HTTP-адрес Consul настраивает приложение отдельно.

Установщику Helm требуется право `get` на выбранный Service в его пространстве
имён. Приложению это право не требуется. Для CI настройка описана в
[правилах Kubernetes-доступа](https://github.com/sitkoru/ci-admin/blob/infra/ci/coredns-lookup-access/docs/kubernetes-access.md).

Проверка настройки по умолчанию без установки ресурсов:

```sh
helm template example charts/dotnet-app --namespace application \
  --dry-run=server
```

Для локального рендеринга без доступа к серверу явно отключите получение DNS:

```sh
helm template example charts/dotnet-app --set consulDns.enabled=false
```

Для проверки включённого получения DNS нужен
`--dry-run=server` и доступ к кластеру.

IP считывается при каждом `helm install` или `helm upgrade`; изменение IP Service
само по себе не обновляет уже запущенные Pod. Требуется следующий `helm upgrade`.
Переменная DNS при включённом параметре и оба gRPC `ExternalAddress` задаются
chart: одноимённые записи в `env` и `environment_env` пропускаются. При выключенном
параметре DNS можно по-прежнему задавать вручную через переменные окружения.

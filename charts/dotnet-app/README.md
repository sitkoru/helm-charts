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
[правилах Kubernetes-доступа](https://github.com/sitkoru/ci-admin/blob/main/docs/kubernetes-access.md).

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

## Пути секретов Vault

Параметр `vaultSecrets` содержит упорядоченный список путей приложения. Если
список непустой, chart задаёт в Deployment `VAULT__SECRETS__0` со значением
`YandexCloud/Common`, а затем пути из списка в указанном порядке. Повторения
`YandexCloud/Common` из списка пропускаются. В Sitko.Core значения из более
поздних путей имеют приоритет над значениями из предыдущих.

```yaml
vaultSecrets:
  - Service/Common
  - Service/Application
```

Для доступа к общему пути роль приложения в Vault должна иметь право его
чтения. Chart не настраивает права и не включает Vault в приложении. Изменение
Deployment вступает в силу при следующем развёртывании; до него права роли
должны быть готовы.

По умолчанию список пуст. При пустом списке chart не добавляет пути и сохраняет
переменные, заданные прежним способом. Для перехода перенесите пути приложения
из `VAULT__SECRETS__N` в `vaultSecrets` в прежнем порядке и удалите старые
переменные из `env`, активного `environment_env`, `secrets` и `b64secrets`.
Непустой список вместе со старой переменной пути в этих источниках приводит к
ошибке рендеринга. Имена старых переменных проверяются без учёта регистра.

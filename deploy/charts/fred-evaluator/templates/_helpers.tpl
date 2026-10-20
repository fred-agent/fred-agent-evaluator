{{- define "fred-evaluator.labels" -}}
app.kubernetes.io/name: fred-evaluator
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end }}

{{- define "fred-evaluator.selectorLabels" -}}
app.kubernetes.io/name: fred-evaluator
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "fred-evaluator.image" -}}
{{- printf "%s:%s" .image.repository (.image.tag | default (printf "v%s" (trimPrefix "v" .root.Chart.AppVersion))) -}}
{{- end }}

{{- define "fred-evaluator.secretName" -}}
{{- if .Values.secret.create -}}
{{ .Release.Name }}-secret
{{- else -}}
{{ .Values.secret.existingSecret }}
{{- end -}}
{{- end }}

{{/*
What both processes share: the configuration file, an empty .env (secrets come
as environment variables, not from a file), extraEnvVars, and the secret as
envFrom when there is one. Without either, no credential reaches the process.
*/}}
{{- define "fred-evaluator.env" -}}
{{- if not (or (include "fred-evaluator.secretName" .) .Values.extraEnvVars) }}
{{- fail "credentials are required: set secret.existingSecret, secret.create, or extraEnvVars" }}
{{- end }}
env:
  - name: CONFIG_FILE
    value: /etc/fred/evaluation/configuration.yaml
  - name: ENV_FILE
    value: /etc/fred/evaluation/empty.env
  {{- with .Values.extraEnvVars }}
  {{- toYaml . | nindent 2 }}
  {{- end }}
{{- with include "fred-evaluator.secretName" . }}
envFrom:
  - secretRef:
      name: {{ . }}
{{- end }}
volumeMounts:
  - name: config
    mountPath: /etc/fred/evaluation
    readOnly: true
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
{{- end }}

{{- define "fred-evaluator.podSpec" -}}
enableServiceLinks: false
securityContext:
  runAsUser: 1000
  runAsGroup: 1000
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
volumes:
  - name: config
    configMap:
      name: {{ .Release.Name }}-config
{{- end }}

{{- define "fred-evaluator.podAnnotations" -}}
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- /* Scraped like Fred's applications: annotations, unless a ServiceMonitor does it. */}}
{{- if and (include "fred-evaluator.metricsPorts" .) (not .Values.metricsService.serviceMonitor.enabled) }}
prometheus.io/scrape: "true"
prometheus.io/port: {{ include "fred-evaluator.metricsPort" . | quote }}
prometheus.io/path: /metrics
{{- end }}
{{- end }}

{{/*
The `metrics` container port of both processes, when the Prometheus KPI sink is
on. An exporter left on loopback is unreachable from Prometheus: refuse it.
*/}}
{{- define "fred-evaluator.metricsPorts" -}}
{{- $prometheus := dig "observability" "kpi" "prometheus" dict .Values.configuration -}}
{{- if $prometheus.enabled }}
{{- $address := $prometheus.address | default "127.0.0.1" }}
{{- if has $address (list "127.0.0.1" "localhost" "::1") }}
{{- fail "configuration.observability.kpi.prometheus.address is a loopback address while the sink is enabled: Prometheus cannot reach it, use 0.0.0.0" }}
{{- end }}
- name: metrics
  containerPort: {{ include "fred-evaluator.metricsPort" . }}
{{- end }}
{{- end }}

{{- define "fred-evaluator.metricsPort" -}}
{{- (dig "observability" "kpi" "prometheus" dict .Values.configuration).port | default 9000 -}}
{{- end }}

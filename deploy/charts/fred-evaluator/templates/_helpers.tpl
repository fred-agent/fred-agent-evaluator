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
{{ required "secret.existingSecret is required unless secret.create is true" .Values.secret.existingSecret }}
{{- end -}}
{{- end }}

{{/*
What both processes share: the configuration file, an empty .env (secrets come
as environment variables, not from a file) and the secret as envFrom.
*/}}
{{- define "fred-evaluator.env" -}}
env:
  - name: CONFIG_FILE
    value: /etc/fred/evaluation/configuration.yaml
  - name: ENV_FILE
    value: /etc/fred/evaluation/empty.env
envFrom:
  - secretRef:
      name: {{ include "fred-evaluator.secretName" . }}
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
{{- end }}

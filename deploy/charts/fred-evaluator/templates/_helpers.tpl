{{- define "fred-evaluator.labels" -}}
app.kubernetes.io/name: fred-evaluator
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
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
Optional extra CA (e.g. a corporate root) trusted for outbound TLS: Keycloak
JWKS and M2M token, model endpoints. Mounted from an existing Secret in its own
directory, so it never shadows the configuration mount and works with a
read-only root filesystem.
*/}}
{{- define "fred-evaluator.trustedCAPath" -}}
/etc/fred/trusted-ca/ca.pem
{{- end }}

{{/*
What both processes share: the configuration file, an empty .env (secrets come
as environment variables, not from a file), extraEnvVars, and the secret as
envFrom when there is one. Without either, no credential reaches the process.
Used by the API, its schema initContainer and the worker alike.
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
  {{- if .Values.trustedCA.existingSecret }}
  - name: SSL_CERT_FILE
    value: {{ include "fred-evaluator.trustedCAPath" . }}
  - name: REQUESTS_CA_BUNDLE
    value: {{ include "fred-evaluator.trustedCAPath" . }}
  {{- end }}
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
  {{- if .Values.trustedCA.existingSecret }}
  - name: trusted-ca
    mountPath: /etc/fred/trusted-ca
    readOnly: true
  {{- end }}
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
  {{- if .Values.trustedCA.existingSecret }}
  - name: trusted-ca
    secret:
      secretName: {{ .Values.trustedCA.existingSecret | quote }}
      items:
        - key: {{ .Values.trustedCA.key | default "ca.crt" | quote }}
          path: ca.pem
  {{- end }}
{{- end }}

{{/*
Restart the pods when the configuration or, with secret.create, the secret
values change: both are read only at start-up.
*/}}
{{- define "fred-evaluator.podAnnotations" -}}
checksum/config: {{ include (print .Template.BasePath "/configmap.yaml") . | sha256sum }}
{{- if .Values.secret.create }}
checksum/secret: {{ .Values.secret.data | toJson | sha256sum }}
{{- end }}
{{- end }}

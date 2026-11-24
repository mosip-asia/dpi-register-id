{{- define "register-id.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "register-id.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "register-id.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "register-id.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "register-id.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "register-id.selectorLabels" -}}
app.kubernetes.io/name: {{ include "register-id.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "register-id.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s/%s@%s" .Values.image.registry .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}

{{/*
Public host the Sandbox Kit should route. This chart does not render an Ingress.
publicHost.host wins. Otherwise <hostname>.<domain> when domain is set.
ingress.host / ingress.domain remain accepted so older values still resolve.
*/}}
{{- define "register-id.host" -}}
{{- if and .Values.publicHost .Values.publicHost.host -}}
{{- .Values.publicHost.host -}}
{{- else if and .Values.publicHost .Values.publicHost.domain -}}
{{- printf "%s.%s" (default "register" .Values.publicHost.hostname) .Values.publicHost.domain -}}
{{- else if and .Values.ingress .Values.ingress.host -}}
{{- .Values.ingress.host -}}
{{- else if and .Values.ingress .Values.ingress.domain -}}
{{- printf "%s.%s" (default "register" .Values.ingress.hostname) .Values.ingress.domain -}}
{{- end -}}
{{- end -}}

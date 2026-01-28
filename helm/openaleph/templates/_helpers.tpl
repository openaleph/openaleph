{{/*
Expand the name of the chart.
*/}}
{{- define "openaleph.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "openaleph.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "openaleph.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "openaleph.labels" -}}
helm.sh/chart: {{ include "openaleph.chart" . }}
{{ include "openaleph.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "openaleph.selectorLabels" -}}
app.kubernetes.io/name: {{ include "openaleph.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "openaleph.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "openaleph.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Return the image tag
*/}}
{{- define "openaleph.imageTag" -}}
{{- .tag | default $.global.image.tag | default "latest" }}
{{- end }}

{{/*
Return the proper image name for a component
*/}}
{{- define "openaleph.image" -}}
{{- $registry := .image.registry | default .global.image.registry -}}
{{- $repository := .image.repository -}}
{{- $tag := .image.tag | default .global.image.tag | default "latest" -}}
{{- if $registry -}}
{{- printf "%s:%s" $repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end }}

{{/*
Common environment variables from ConfigMap and Secrets
*/}}
{{- define "openaleph.commonEnvFrom" -}}
- configMapRef:
    name: {{ include "openaleph.fullname" . }}-env
- secretRef:
    name: {{ include "openaleph.fullname" . }}-secrets
{{- end }}

{{/*
Component labels
*/}}
{{- define "openaleph.componentLabels" -}}
app.kubernetes.io/component: {{ .component }}
{{- end }}

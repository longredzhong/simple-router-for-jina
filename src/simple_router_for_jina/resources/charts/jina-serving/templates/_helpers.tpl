{{- define "jina-serving.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "jina-serving.fullname" -}}
{{- default .Release.Name .Values.nameOverride | trunc 52 | trimSuffix "-" -}}
{{- end -}}

{{- define "jina-serving.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "jina-serving.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "jina-serving.commonLabels" -}}
app.kubernetes.io/name: {{ include "jina-serving.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- range $key, $value := .Values.commonLabels }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end -}}

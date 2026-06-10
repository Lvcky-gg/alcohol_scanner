import { defineStore } from 'pinia'
import { ref } from 'vue'

type CanonicalFields = {
  brandName: string | null
  classType: string | null
  alcoholContent: string | null
  netContents: string | null
  countryOfOrigin: string | null
  producer: string | null
  governmentWarning: string | null
}

type FieldKey = keyof CanonicalFields

type FieldStatus = 'pass' | 'review' | 'fail'

type FieldResult = {
  label: string
  value: string | null
  confidence: number | null
  status: FieldStatus
}

type UiResult = {
  fields: CanonicalFields
  rows: FieldResult[]
}

const FIELD_META: Record<FieldKey, string> = {
  brandName: 'Brand Name',
  classType: 'Class / Type',
  alcoholContent: 'Alcohol Content',
  netContents: 'Net Contents',
  countryOfOrigin: 'Country of Origin',
  producer: 'Producer',
  governmentWarning: 'Government Warning',
}

function toStatus(confidence: number | null, value: string | null): FieldStatus {
  if (!value) return 'fail'
  if (confidence == null) return 'review'
  if (confidence >= 0.8) return 'pass'
  if (confidence >= 0.6) return 'review'
  return 'fail'
}

export const useVerificationStore = defineStore('verification', () => {
  const loading = ref(false)
  const error = ref<string | null>(null)
  const result = ref<UiResult | null>(null)
  const previewUrl = ref<string | null>(null)

  async function verifyWithOllama(file: File): Promise<void> {
    loading.value = true
    error.value = null

    try {
      const formData = new FormData()
      formData.append('file', file)

      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:5000'
      const response = await fetch(`${baseUrl}/verify/ollama`, {
        method: 'POST',
        body: formData,
      })

      const contentType = response.headers.get('content-type') || ''
      const isJson = contentType.includes('application/json')
      const payload = isJson ? await response.json() : null

      if (!isJson) {
        const bodyText = await response.text()
        const preview = bodyText.slice(0, 200).replace(/\s+/g, ' ').trim()
        throw new Error(`API returned non-JSON (${response.status}): ${preview || 'empty response'}`)
      }

      if (!response.ok) {
        throw new Error(payload?.error || 'Verification failed')
      }

      const canonical = payload?.canonicalFields ?? payload?.finalFields ?? {}
      const confidence = payload?.ollamaVerification?.parsed?.confidence ?? {}

      const ruleChecks: Array<{ field: string; status: string; detected: string | null }> =
        payload?.ruleVerification?.checks ?? []
      const govCheck = ruleChecks.find((c) => c.field === 'government_warning')
      const govDetected = govCheck?.detected || null

      const ollamaParsed = payload?.ollamaVerification?.parsed ?? {}
      const ollamaPresent: boolean | null = ollamaParsed?.governmentWarningPresent ?? null
      const ollamaValid: boolean | null = ollamaParsed?.governmentWarningValid ?? null
      const ollamaGovConfidence: number | null = ollamaParsed?.confidence?.governmentWarning ?? null

      // Determine row status: rule check takes precedence; fall back to Ollama inference
      let govStatus: string | null = govCheck?.status ?? null
      if (!govStatus) {
        if (ollamaValid === true) govStatus = 'pass'
        else if (ollamaPresent === true && ollamaValid === false) govStatus = 'review'
        else if (ollamaPresent === true) govStatus = 'review'
        else if (ollamaPresent === false) govStatus = 'fail'
        else govStatus = null
      }
      // Surface Ollama evidence in the value when rule check found nothing
      const govDisplayValue =
        govDetected ??
        (ollamaPresent === true ? 'Detected by Ollama (unreadable by OCR)' : null)

      const fields: CanonicalFields = {
        brandName: canonical.brandName ?? null,
        classType: canonical.classType ?? null,
        alcoholContent: canonical.alcoholContent ?? null,
        netContents: canonical.netContents ?? null,
        countryOfOrigin: canonical.countryOfOrigin ?? null,
        producer: canonical.producer ?? null,
        governmentWarning: govDisplayValue,
      }

      const rows: FieldResult[] = (Object.keys(FIELD_META) as FieldKey[]).map((key) => {
        if (key === 'governmentWarning') {
          const ruleFieldStatus = (govStatus as FieldStatus | null) ?? toStatus(null, govDisplayValue)
          return {
            label: FIELD_META[key],
            value: govDisplayValue,
            confidence: ollamaGovConfidence,
            status: ruleFieldStatus,
          }
        }
        const value = fields[key]
        const scoreRaw = confidence[key]
        const score = typeof scoreRaw === 'number' ? scoreRaw : null
        return {
          label: FIELD_META[key],
          value,
          confidence: score,
          status: toStatus(score, value),
        }
      })

      if (previewUrl.value) {
        URL.revokeObjectURL(previewUrl.value)
      }
      previewUrl.value = URL.createObjectURL(file)

      result.value = { fields, rows }
    } catch (err) {
      error.value = err instanceof Error ? err.message : 'Unexpected verification error'
      result.value = null
    } finally {
      loading.value = false
    }
  }

  function reset(): void {
    error.value = null
    result.value = null
    if (previewUrl.value) {
      URL.revokeObjectURL(previewUrl.value)
      previewUrl.value = null
    }
  }

  return {
    loading,
    error,
    result,
    previewUrl,
    verifyWithOllama,
    reset,
  }
})

<script setup lang="ts">
import { computed, ref } from 'vue'
import Button from 'primevue/button'
import Card from 'primevue/card'
import Divider from 'primevue/divider'
import Message from 'primevue/message'
import ProgressSpinner from 'primevue/progressspinner'
import Tag from 'primevue/tag'
import { useVerificationStore } from './stores/verification'

const store = useVerificationStore()
const selectedFile = ref<File | null>(null)

const fileName = computed(() => selectedFile.value?.name || 'No file selected')
const fieldRows = computed(() => store.result?.rows || [])

function confidenceLabel(value: number | null): string {
  if (value == null) return 'N/A'
  return `${Math.round(value * 100)}%`
}

function severityFromStatus(status: 'pass' | 'review' | 'fail') {
  if (status === 'pass') return 'success'
  if (status === 'review') return 'warn'
  return 'danger'
}

function onPickFile(event: Event): void {
  const input = event.target as HTMLInputElement
  const nextFile = input.files?.[0] || null
  selectedFile.value = nextFile
}

async function onVerify(): Promise<void> {
  if (!selectedFile.value) return
  await store.verifyWithOllama(selectedFile.value)
}
</script>

<template>
  <main class="tactical-shell min-h-screen px-4 py-6 md:px-8 md:py-10">
    <section class="mx-auto grid w-full max-w-6xl gap-6 lg:grid-cols-[1.1fr_1fr]">
      <Card class="tactical-panel overflow-hidden">
        <template #title>
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="text-xs tracking-[0.35em] text-[var(--tac-mint)]">LABEL OPS</p>
              <h1 class="mt-2 text-3xl font-bold text-[var(--tac-ice)] md:text-4xl">TACTICAL VERIFICATION</h1>
            </div>
            <Tag severity="contrast" value="LIVE" class="tracking-widest" />
          </div>
        </template>

        <template #content>
          <p class="mb-6 max-w-xl text-sm text-[var(--tac-fog)] md:text-base">
            Upload a label image and run OCR + Ollama canonical extraction.
          </p>

          <div class="grid gap-4 rounded-xl border border-[var(--tac-border)] bg-[var(--tac-panel-soft)] p-4">
            <label class="text-xs tracking-[0.3em] text-[var(--tac-fog)]">IMAGE INPUT</label>
            <input type="file" accept="image/*" class="tactical-file" @change="onPickFile" />

            <div class="flex items-center justify-between gap-3">
              <p class="truncate font-mono text-xs text-[var(--tac-ice)]">{{ fileName }}</p>
              <Button label="Run Verification" icon="pi pi-bolt" :disabled="!selectedFile || store.loading"
                :loading="store.loading" @click="onVerify" />
            </div>
          </div>

          <Message v-if="store.error" severity="error" class="mt-4">{{ store.error }}</Message>

          <div v-if="store.loading"
            class="mt-6 flex items-center gap-3 rounded-xl border border-[var(--tac-border)] p-4">
            <ProgressSpinner style="width: 28px; height: 28px" strokeWidth="8" />
            <p class="font-mono text-sm text-[var(--tac-ice)]">Scanning label signatures...</p>
          </div>

          <div v-if="store.previewUrl"
            class="mt-6 rounded-xl border border-[var(--tac-border)] bg-[var(--tac-panel-soft)] p-4">
            <p class="mb-3 text-xs tracking-[0.3em] text-[var(--tac-fog)]">IMAGE PREVIEW</p>
            <img :src="store.previewUrl" alt="Uploaded label" class="tactical-preview" />
          </div>
        </template>
      </Card>

      <Card class="tactical-panel overflow-hidden">
        <template #title>
          <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-[var(--tac-ice)]">Canonical Output</h2>
            <Button icon="pi pi-refresh" text rounded aria-label="Reset" @click="store.reset" />
          </div>
        </template>

        <template #content>
          <div v-if="!store.result" class="rounded-xl border border-dashed border-[var(--tac-border)] p-8 text-center">
            <p class="text-sm text-[var(--tac-fog)]">No payload yet. Upload a label to generate tactical JSON output.
            </p>
          </div>

          <div v-else class="space-y-3">
            <div v-for="row in fieldRows" :key="row.label"
              class="rounded-xl border border-[var(--tac-border)] bg-[var(--tac-panel-soft)] p-4 tactical-row">
              <div class="flex items-start justify-between gap-2">
                <p class="text-xs tracking-[0.28em] text-[var(--tac-fog)]">{{ row.label }}</p>
                <Tag :severity="severityFromStatus(row.status)" :value="row.status.toUpperCase()" />
              </div>
              <Divider class="my-2" />
              <p class="font-['Share_Tech_Mono'] text-sm text-[var(--tac-ice)] md:text-base">{{ row.value || 'null' }}
              </p>
              <p class="mt-2 text-xs tracking-[0.2em] text-[var(--tac-fog)]">CONFIDENCE: {{
                confidenceLabel(row.confidence) }}</p>
            </div>
          </div>
        </template>
      </Card>
    </section>
  </main>
</template>

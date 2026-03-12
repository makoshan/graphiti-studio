<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Header -->
    <header class="bg-white border-b border-gray-200 sticky top-0 z-30">
      <div class="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <router-link
            to="/"
            class="p-1.5 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M15 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </router-link>
          <h1 class="text-xl font-bold text-gray-900">Settings</h1>
        </div>
        <button
          @click="saveSettings"
          :disabled="saving"
          class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
        >
          {{ saving ? 'Saving...' : 'Save Settings' }}
        </button>
      </div>
    </header>

    <main class="max-w-3xl mx-auto px-6 py-8 space-y-8">
      <!-- LLM Configuration -->
      <section class="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-6 py-4 border-b border-gray-100">
          <h2 class="text-base font-semibold text-gray-900">LLM Configuration</h2>
          <p class="text-sm text-gray-500 mt-1">Configure the language model used for chat and analysis.</p>
        </div>
        <div class="px-6 py-5 space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
            <input
              v-model="settings.llm_api_key"
              type="password"
              placeholder="sk-..."
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
            <input
              v-model="settings.llm_base_url"
              type="text"
              placeholder="https://api.openai.com/v1"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Model Name</label>
            <input
              v-model="settings.llm_model"
              type="text"
              placeholder="gpt-4o"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
        </div>
      </section>

      <!-- Graphiti-Zep Connection -->
      <section class="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-6 py-4 border-b border-gray-100">
          <h2 class="text-base font-semibold text-gray-900">Graphiti-Zep Connection</h2>
          <p class="text-sm text-gray-500 mt-1">Connect to your graphiti-zep knowledge graph backend.</p>
        </div>
        <div class="px-6 py-5 space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Base URL</label>
            <input
              v-model="settings.graphiti_base_url"
              type="text"
              placeholder="http://127.0.0.1:8000"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">API Key</label>
            <input
              v-model="settings.graphiti_api_key"
              type="password"
              placeholder="local-graphiti"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <button
              @click="testConnection"
              :disabled="testing"
              class="px-4 py-2 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              <span v-if="testing" class="w-4 h-4 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin"></span>
              {{ testing ? 'Testing...' : 'Test Connection' }}
            </button>
            <p v-if="testResult" :class="testResult.ok ? 'text-green-600' : 'text-red-600'" class="text-sm mt-2">
              {{ testResult.message }}
            </p>
          </div>
        </div>
      </section>

      <!-- Processing Defaults -->
      <section class="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div class="px-6 py-4 border-b border-gray-100">
          <h2 class="text-base font-semibold text-gray-900">Processing Defaults</h2>
          <p class="text-sm text-gray-500 mt-1">Default settings for document ingestion.</p>
        </div>
        <div class="px-6 py-5 space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Chunk Size (chars)</label>
              <input
                v-model.number="settings.default_chunk_size"
                type="number"
                min="100"
                max="10000"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Chunk Overlap (chars)</label>
              <input
                v-model.number="settings.default_chunk_overlap"
                type="number"
                min="0"
                max="2000"
                class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
              />
            </div>
          </div>
        </div>
      </section>

      <!-- Save notification -->
      <div
        v-if="saveMessage"
        class="fixed bottom-6 right-6 px-4 py-3 bg-green-600 text-white text-sm font-medium rounded-lg shadow-lg transition-all"
      >
        {{ saveMessage }}
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const settings = ref({
  llm_api_key: '',
  llm_base_url: '',
  llm_model: '',
  graphiti_base_url: 'http://127.0.0.1:8000',
  graphiti_api_key: 'local-graphiti',
  default_chunk_size: 1000,
  default_chunk_overlap: 200
})

const saving = ref(false)
const testing = ref(false)
const testResult = ref(null)
const saveMessage = ref('')

const loadSettings = async () => {
  try {
    const res = await api.get('/api/settings')
    const data = res.settings || res.data?.settings || res
    settings.value = { ...settings.value, ...data }
  } catch (error) {
    console.error('Failed to load settings:', error)
  }
}

const saveSettings = async () => {
  saving.value = true
  try {
    await api.put('/api/settings', settings.value)
    saveMessage.value = 'Settings saved successfully'
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (error) {
    console.error('Failed to save settings:', error)
    alert('Failed to save settings. Please try again.')
  } finally {
    saving.value = false
  }
}

const testConnection = async () => {
  testing.value = true
  testResult.value = null
  try {
    const res = await api.post('/api/settings/test-connection', {
      graphiti_base_url: settings.value.graphiti_base_url,
      graphiti_api_key: settings.value.graphiti_api_key
    })
    testResult.value = { ok: true, message: res.message || 'Connection successful' }
  } catch (error) {
    testResult.value = { ok: false, message: error.message || 'Connection failed' }
  } finally {
    testing.value = false
  }
}

onMounted(loadSettings)
</script>

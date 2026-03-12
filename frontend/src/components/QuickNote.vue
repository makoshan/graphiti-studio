<template>
  <div class="bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
    <div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-900">Quick Note</h3>
      <button @click="$emit('close')" class="text-gray-400 hover:text-gray-600 transition-colors">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <div class="p-4">
      <textarea
        v-model="noteContent"
        placeholder="Type a note to save to your knowledge graph..."
        rows="4"
        class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
      ></textarea>

      <!-- Success message -->
      <div v-if="successMsg" class="mt-2 px-3 py-2 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
        {{ successMsg }}
      </div>

      <!-- Error message -->
      <div v-if="errorMsg" class="mt-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
        {{ errorMsg }}
      </div>

      <button
        @click="saveNote"
        :disabled="!noteContent.trim() || saving"
        class="mt-3 w-full px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
      >
        {{ saving ? 'Saving...' : 'Save to Graph' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api from '../api'

const props = defineProps({
  projectId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['close'])

const noteContent = ref('')
const saving = ref(false)
const successMsg = ref('')
const errorMsg = ref('')

const saveNote = async () => {
  if (!noteContent.value.trim() || saving.value) return

  saving.value = true
  successMsg.value = ''
  errorMsg.value = ''

  try {
    await api.post('/api/memory/capture', {
      project_id: props.projectId,
      content: noteContent.value.trim()
    })

    successMsg.value = 'Note saved to knowledge graph successfully.'
    noteContent.value = ''
    setTimeout(() => { successMsg.value = '' }, 3000)
  } catch (error) {
    console.error('Failed to save note:', error)
    errorMsg.value = error.message || 'Failed to save note. Please try again.'
  } finally {
    saving.value = false
  }
}
</script>

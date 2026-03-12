<template>
  <div class="bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
    <div class="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
      <h3 class="text-sm font-semibold text-gray-900">Upload Documents</h3>
      <button @click="$emit('close')" class="text-gray-400 hover:text-gray-600 transition-colors">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
    </div>

    <div class="p-4">
      <!-- Drop zone -->
      <div
        @dragover.prevent="dragActive = true"
        @dragleave="dragActive = false"
        @drop.prevent="handleDrop"
        @click="fileInput?.click()"
        :class="[
          'border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all',
          dragActive
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50'
        ]"
      >
        <svg class="w-8 h-8 text-gray-400 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <p class="text-sm text-gray-600 mb-1">Drop files here or click to browse</p>
        <p class="text-xs text-gray-400">Supports .txt, .md, .pdf</p>
      </div>

      <input
        ref="fileInput"
        type="file"
        multiple
        accept=".txt,.md,.pdf"
        class="hidden"
        @change="handleFileSelect"
      />

      <!-- Selected files -->
      <div v-if="selectedFiles.length > 0" class="mt-3 space-y-2">
        <div
          v-for="(file, idx) in selectedFiles"
          :key="idx"
          class="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg text-sm"
        >
          <div class="flex items-center gap-2 min-w-0">
            <svg class="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            <span class="truncate">{{ file.name }}</span>
            <span class="text-xs text-gray-400 flex-shrink-0">{{ formatSize(file.size) }}</span>
          </div>
          <button @click="removeFile(idx)" class="text-gray-400 hover:text-red-500 flex-shrink-0">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Upload progress -->
      <div v-if="uploading" class="mt-3">
        <div class="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>Uploading...</span>
          <span>{{ uploadProgress }}%</span>
        </div>
        <div class="w-full bg-gray-200 rounded-full h-1.5">
          <div class="bg-indigo-600 h-1.5 rounded-full transition-all" :style="{ width: uploadProgress + '%' }"></div>
        </div>
      </div>

      <!-- Result -->
      <div v-if="uploadResult" class="mt-3 px-3 py-2 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
        {{ uploadResult }}
      </div>

      <!-- Error -->
      <div v-if="uploadError" class="mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
        {{ uploadError }}
      </div>

      <!-- Upload button -->
      <button
        v-if="selectedFiles.length > 0 && !uploading"
        @click="uploadFiles"
        class="mt-3 w-full px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
      >
        Upload {{ selectedFiles.length }} file{{ selectedFiles.length > 1 ? 's' : '' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  projectId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['uploaded', 'close'])

const fileInput = ref(null)
const selectedFiles = ref([])
const dragActive = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadResult = ref('')
const uploadError = ref('')

const ACCEPTED_TYPES = ['.txt', '.md', '.pdf']

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files))
  event.target.value = ''
}

const handleDrop = (event) => {
  dragActive.value = false
  addFiles(Array.from(event.dataTransfer.files))
}

const addFiles = (files) => {
  const validFiles = files.filter(f => {
    const ext = '.' + f.name.split('.').pop().toLowerCase()
    return ACCEPTED_TYPES.includes(ext)
  })
  selectedFiles.value = [...selectedFiles.value, ...validFiles]
  uploadResult.value = ''
  uploadError.value = ''
}

const removeFile = (idx) => {
  selectedFiles.value.splice(idx, 1)
}

const formatSize = (bytes) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

const uploadFiles = async () => {
  if (selectedFiles.value.length === 0) return

  uploading.value = true
  uploadProgress.value = 0
  uploadResult.value = ''
  uploadError.value = ''

  try {
    const formData = new FormData()
    selectedFiles.value.forEach(file => {
      formData.append('files', file)
    })

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `/api/projects/${props.projectId}/upload`)

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        uploadProgress.value = Math.round((e.loaded / e.total) * 100)
      }
    })

    const result = await new Promise((resolve, reject) => {
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText))
          } catch {
            resolve({ chunks_created: 0 })
          }
        } else {
          reject(new Error(`Upload failed: ${xhr.status}`))
        }
      }
      xhr.onerror = () => reject(new Error('Network error'))
      xhr.send(formData)
    })

    const chunks = result.chunks_created || result.data?.chunks_created || 0
    uploadResult.value = `Successfully created ${chunks} chunk${chunks !== 1 ? 's' : ''} from ${selectedFiles.value.length} file${selectedFiles.value.length > 1 ? 's' : ''}.`
    selectedFiles.value = []
    emit('uploaded')
  } catch (error) {
    console.error('Upload failed:', error)
    uploadError.value = error.message || 'Upload failed. Please try again.'
  } finally {
    uploading.value = false
  }
}
</script>

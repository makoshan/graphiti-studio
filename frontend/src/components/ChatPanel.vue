<template>
  <div class="flex flex-col h-full bg-white">
    <!-- Chat header with thread switcher -->
    <div class="px-4 py-2.5 border-b border-gray-100 flex-shrink-0">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-semibold text-gray-900">Chat</h3>
          <button
            @click="showThreads = !showThreads"
            class="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors px-1.5 py-0.5 rounded hover:bg-gray-50"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            {{ threads.length }} threads
            <svg :class="['w-3 h-3 transition-transform', showThreads ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
        <button
          @click="startNewChat"
          class="text-xs text-gray-400 hover:text-indigo-600 transition-colors flex items-center gap-1"
          title="New conversation"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path d="M12 4v16m8-8H4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          New
        </button>
      </div>

      <!-- Thread list dropdown -->
      <div v-if="showThreads" class="mt-2 border border-gray-200 rounded-lg max-h-48 overflow-y-auto bg-gray-50">
        <div v-if="threads.length === 0" class="px-3 py-2 text-xs text-gray-400 text-center">
          No threads yet
        </div>
        <div
          v-for="thread in threads"
          :key="thread.id"
          @click="switchThread(thread)"
          :class="[
            'flex items-center justify-between px-3 py-2 cursor-pointer text-xs transition-colors border-b border-gray-100 last:border-b-0',
            thread.id === chat.currentThreadId.value
              ? 'bg-indigo-50 text-indigo-700'
              : 'text-gray-600 hover:bg-white'
          ]"
        >
          <div class="flex-1 min-w-0">
            <p class="truncate font-medium">{{ thread.title || 'Untitled' }}</p>
            <p class="text-[10px] text-gray-400 mt-0.5">{{ formatDate(thread.created_at) }}</p>
          </div>
          <button
            @click.stop="deleteThread(thread.id)"
            class="ml-2 p-0.5 text-gray-300 hover:text-red-500 transition-colors flex-shrink-0"
            title="Delete thread"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M6 18L18 6M6 6l12 12" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Messages -->
    <div ref="messagesContainer" class="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      <!-- Empty state -->
      <div v-if="chat.messages.value.length === 0" class="flex flex-col items-center justify-center h-full text-center px-8">
        <div class="w-12 h-12 bg-indigo-50 rounded-xl flex items-center justify-center mb-3">
          <svg class="w-6 h-6 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <p class="text-sm font-medium text-gray-900 mb-1">Ask about your graph</p>
        <p class="text-xs text-gray-400">Query entities, relationships, and insights from your knowledge graph.</p>
      </div>

      <!-- Message list -->
      <div
        v-for="(msg, idx) in chat.messages.value"
        :key="idx"
        :class="msg.role === 'user' ? 'flex justify-end' : 'flex justify-start'"
      >
        <div
          :class="[
            'max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
            msg.role === 'user'
              ? 'bg-indigo-600 text-white rounded-br-md'
              : 'bg-gray-100 text-gray-800 rounded-bl-md'
          ]"
        >
          <!-- Message content -->
          <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)" class="prose prose-sm max-w-none prose-p:my-1 prose-headings:my-2 prose-pre:bg-gray-800 prose-pre:text-gray-100"></div>
          <div v-else>{{ msg.content }}</div>

          <!-- Assistant message actions -->
          <div v-if="msg.role === 'assistant' && msg.content" class="flex items-center gap-2 mt-2 pt-2 border-t border-gray-200/50">
            <button
              @click="saveToGraph(msg.content)"
              class="text-xs text-gray-400 hover:text-indigo-600 transition-colors flex items-center gap-1"
              title="Save to graph"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              Save
            </button>
            <button
              @click="copyText(msg.content)"
              class="text-xs text-gray-400 hover:text-indigo-600 transition-colors flex items-center gap-1"
              title="Copy"
            >
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              Copy
            </button>
          </div>

          <!-- References -->
          <div v-if="hasReferences(msg)" class="mt-2 pt-2 border-t border-gray-200/50">
            <p class="text-xs text-gray-500 mb-1 font-medium">References:</p>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="node in normalizeRefs(msg.references?.nodes)"
                :key="node.uuid"
                @click="$emit('reference-click', node.uuid)"
                class="text-xs px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full hover:bg-indigo-100 transition-colors underline decoration-dotted"
              >
                {{ node.name }}
              </button>
              <span
                v-for="edge in normalizeRefs(msg.references?.edges)"
                :key="edge.uuid"
                class="text-xs px-2 py-0.5 bg-emerald-50 text-emerald-700 rounded-full"
              >
                {{ edge.name }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Streaming / tool indicator -->
      <div v-if="chat.streaming.value" class="flex justify-start">
        <div class="bg-gray-100 text-gray-500 rounded-2xl rounded-bl-md px-4 py-3 text-sm flex items-center gap-2">
          <span class="flex gap-1">
            <span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms"></span>
            <span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms"></span>
            <span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms"></span>
          </span>
          <span class="text-xs">{{ chat.toolStatus.value || 'Thinking...' }}</span>
        </div>
      </div>
    </div>

    <!-- Input area -->
    <div class="px-4 py-3 border-t border-gray-100 flex-shrink-0">
      <div class="flex items-end gap-2">
        <textarea
          ref="inputEl"
          v-model="inputText"
          @keydown.enter.exact.prevent="handleSend"
          placeholder="Ask a question about your graph..."
          rows="1"
          class="flex-1 px-3 py-2 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none max-h-32 overflow-y-auto"
          :disabled="chat.streaming.value"
        ></textarea>
        <button
          @click="handleSend"
          :disabled="!inputText.trim() || chat.streaming.value"
          class="p-2 bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 transition-colors disabled:opacity-40 disabled:hover:bg-indigo-600 flex-shrink-0"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path d="M12 19V5m0 0l-7 7m7-7l7 7" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, toRef, onMounted } from 'vue'
import { marked } from 'marked'
import { useChat } from '../composables/useChat'
import api from '../api'

const props = defineProps({
  projectId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['reference-click', 'references-updated'])

const projectIdRef = toRef(props, 'projectId')
const chat = useChat(projectIdRef)

const inputText = ref('')
const inputEl = ref(null)
const messagesContainer = ref(null)
const showThreads = ref(false)
const threads = ref([])

// --- Thread management ---

const fetchThreads = async ({ autoselect = false } = {}) => {
  try {
    const res = await api.get(`/api/projects/${props.projectId}/threads`)
    threads.value = res.data || res || []
    if (
      autoselect &&
      !chat.streaming.value &&
      !chat.currentThreadId.value &&
      threads.value.length > 0
    ) {
      await chat.loadThread(threads.value[0].id)
    }
  } catch (error) {
    console.error('Failed to fetch threads:', error)
  }
}

const switchThread = async (thread) => {
  await chat.loadThread(thread.id)
  showThreads.value = false
}

const startNewChat = () => {
  chat.clearMessages()
  showThreads.value = false
  emit('references-updated', { nodes: [], edges: [] })
  fetchThreads()
}

const deleteThread = async (threadId) => {
  try {
    await api.delete(`/api/projects/${props.projectId}/threads/${threadId}`)
    threads.value = threads.value.filter(t => t.id !== threadId)
    if (chat.currentThreadId.value === threadId) {
      chat.clearMessages()
      emit('references-updated', { nodes: [], edges: [] })
    }
  } catch (error) {
    console.error('Failed to delete thread:', error)
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    const now = new Date()
    const diffMs = now - d
    const diffDays = Math.floor(diffMs / 86400000)
    if (diffDays === 0) return 'Today'
    if (diffDays === 1) return 'Yesterday'
    if (diffDays < 7) return `${diffDays}d ago`
    return d.toLocaleDateString()
  } catch {
    return dateStr
  }
}

// --- References normalization ---
// Handles both UUID strings and {uuid, name} objects from the backend.

const normalizeRefs = (refs) => {
  if (!refs || !Array.isArray(refs)) return []
  return refs.map(r => {
    if (typeof r === 'string') {
      return { uuid: r, name: r.slice(0, 8) + '...' }
    }
    return { uuid: r.uuid || r.id || '', name: r.name || r.fact || (r.uuid || '').slice(0, 8) }
  })
}

const hasReferences = (msg) => {
  if (!msg.references) return false
  const nodes = msg.references.nodes || []
  const edges = msg.references.edges || []
  return nodes.length > 0 || edges.length > 0
}

// --- Rendering ---

const renderMarkdown = (text) => {
  if (!text) return ''
  try {
    return marked.parse(text, { breaks: true })
  } catch {
    return text
  }
}

const handleSend = () => {
  if (!inputText.value.trim() || chat.streaming.value) return
  chat.send(inputText.value)
  inputText.value = ''
  nextTick(() => {
    if (inputEl.value) {
      inputEl.value.style.height = 'auto'
    }
  })
}

const copyText = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    console.error('Failed to copy text')
  }
}

const saveToGraph = async (content) => {
  try {
    await api.post('/api/memory/capture', {
      project_id: props.projectId,
      content: content
    })
  } catch (error) {
    console.error('Failed to save to graph:', error)
  }
}

// Auto-scroll on new messages
watch(
  () => chat.messages.value.length,
  () => {
    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  }
)

// Auto-scroll during streaming
watch(
  () => chat.messages.value[chat.messages.value.length - 1]?.content,
  () => {
    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  }
)

// Auto-resize textarea
watch(inputText, () => {
  nextTick(() => {
    if (inputEl.value) {
      inputEl.value.style.height = 'auto'
      inputEl.value.style.height = Math.min(inputEl.value.scrollHeight, 128) + 'px'
    }
  })
})

// Refresh thread list when streaming ends (new thread may have been created)
watch(() => chat.streaming.value, (streaming) => {
  if (!streaming) {
    fetchThreads()
  }
})

// Emit references to parent when they change (for auto-highlight in GraphPanel)
watch(() => chat.currentReferences.value, (refs) => {
  const nodeUuids = (refs?.nodes || []).map(n => typeof n === 'string' ? n : n.uuid).filter(Boolean)
  const edgeUuids = (refs?.edges || []).map(e => typeof e === 'string' ? e : e.uuid).filter(Boolean)
  emit('references-updated', { nodes: nodeUuids, edges: edgeUuids })
}, { deep: true })

onMounted(() => {
  fetchThreads({ autoselect: true })
})

watch(projectIdRef, () => {
  chat.clearMessages()
  showThreads.value = false
  fetchThreads({ autoselect: true })
})
</script>

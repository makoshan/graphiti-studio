<template>
  <div class="h-screen flex flex-col bg-gray-50">
    <!-- Header -->
    <header class="bg-white border-b border-gray-200 flex-shrink-0 z-20">
      <div class="px-4 py-3 flex items-center justify-between gap-4">
        <!-- Left: back + project name -->
        <div class="flex items-center gap-3 min-w-0">
          <button
            @click="$router.push('/')"
            class="p-1.5 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M15 19l-7-7 7-7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <button
            @click="sidebarOpen = !sidebarOpen"
            class="p-1.5 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
            title="Toggle project sidebar"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M4 6h16M4 12h16M4 18h7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <h1 class="text-base font-semibold text-gray-900 truncate">{{ project?.name || 'Loading...' }}</h1>
          <span v-if="project" class="text-xs text-gray-400 flex-shrink-0">
            {{ project.node_count || 0 }} nodes / {{ project.edge_count || 0 }} edges
          </span>
        </div>

        <!-- Center: view mode toggle -->
        <div class="flex items-center bg-gray-100 rounded-lg p-0.5 flex-shrink-0">
          <button
            v-for="mode in viewModes"
            :key="mode.key"
            @click="viewMode = mode.key"
            :class="[
              'px-3 py-1.5 text-xs font-medium rounded-md transition-all',
              viewMode === mode.key
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            ]"
          >
            {{ mode.label }}
          </button>
        </div>

        <!-- Right: actions -->
        <div class="flex items-center gap-2 flex-shrink-0">
          <button
            @click="showUpload = !showUpload"
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            Upload
          </button>
          <button
            @click="showQuickNote = !showQuickNote"
            class="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            Note
          </button>
          <!-- Export -->
          <button
            @click="exportProject"
            class="p-1.5 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Export project"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
          <button
            @click="refreshGraph"
            :disabled="graphLoading"
            class="p-1.5 text-gray-400 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh graph"
          >
            <svg class="w-5 h-5" :class="{ 'animate-spin': graphLoading }" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </header>

    <!-- Upload overlay -->
    <div v-if="showUpload" class="absolute top-16 right-4 z-30 w-96">
      <UploadZone :projectId="projectId" @uploaded="onUploaded" @close="showUpload = false" />
    </div>

    <!-- Quick Note overlay -->
    <div v-if="showQuickNote" class="absolute top-16 right-4 z-30 w-96">
      <QuickNote :projectId="projectId" @close="showQuickNote = false" />
    </div>

    <!-- Body: optional sidebar + main content -->
    <div class="flex-1 flex overflow-hidden relative">
      <!-- Left sidebar: project list (collapsible) -->
      <aside
        v-if="sidebarOpen"
        class="w-56 bg-white border-r border-gray-200 flex-shrink-0 flex flex-col overflow-hidden"
      >
        <div class="px-3 py-2.5 border-b border-gray-100">
          <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Projects</p>
        </div>
        <div class="flex-1 overflow-y-auto">
          <div
            v-for="p in projects"
            :key="p.id"
            @click="$router.push(`/project/${p.id}`)"
            :class="[
              'px-3 py-2 cursor-pointer border-b border-gray-50 transition-colors',
              p.id === projectId ? 'bg-indigo-50 border-l-2 border-l-indigo-500' : 'hover:bg-gray-50'
            ]"
          >
            <p :class="['text-sm truncate', p.id === projectId ? 'font-semibold text-indigo-700' : 'text-gray-700']">
              {{ p.name }}
            </p>
            <p class="text-[10px] text-gray-400 mt-0.5">
              {{ p.node_count || 0 }} nodes / {{ p.edge_count || 0 }} edges
            </p>
          </div>
        </div>
        <!-- Quick actions at bottom -->
        <div class="border-t border-gray-100 p-2 space-y-1">
          <button
            @click="showUpload = true"
            class="w-full text-left text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 rounded hover:bg-gray-50 transition-colors flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            Upload files
          </button>
          <button
            @click="showQuickNote = true"
            class="w-full text-left text-xs text-gray-500 hover:text-gray-700 px-2 py-1.5 rounded hover:bg-gray-50 transition-colors flex items-center gap-2"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
            Quick note
          </button>
        </div>
      </aside>

      <!-- Main content area -->
      <div class="flex-1 flex overflow-hidden">
        <!-- Graph view -->
        <div
          v-if="viewMode === 'graph' || viewMode === 'split'"
          :class="viewMode === 'split' ? 'w-1/2 border-r border-gray-200' : 'w-full'"
          class="h-full"
        >
          <GraphPanel
            :projectId="projectId"
            :graphData="graphData"
            :loading="graphLoading"
            :highlightNodes="highlightNodes"
            :highlightEdges="highlightEdges"
            @refresh="refreshGraph"
          />
        </div>

        <!-- Chat view -->
        <div
          v-if="viewMode === 'chat' || viewMode === 'split'"
          :class="viewMode === 'split' ? 'w-1/2' : 'w-full'"
          class="h-full"
        >
          <ChatPanel
            :projectId="projectId"
            @reference-click="handleReferenceClick"
            @references-updated="handleReferencesUpdated"
          />
        </div>
      </div>
    </div>

    <!-- Bottom status bar -->
    <footer class="bg-white border-t border-gray-200 px-4 py-1.5 flex items-center justify-between text-[11px] text-gray-400 flex-shrink-0">
      <div class="flex items-center gap-4">
        <span>{{ project?.node_count || 0 }} nodes</span>
        <span>{{ project?.edge_count || 0 }} edges</span>
        <span v-if="memoryStatus">{{ memoryStatus.queue?.pending || 0 }} pending extracts</span>
      </div>
      <div class="flex items-center gap-3">
        <span :class="memoryStatus?.neo4j_ok ? 'text-emerald-500' : 'text-red-400'">
          {{ memoryStatus?.neo4j_ok ? 'Graph connected' : 'Graph offline' }}
        </span>
        <span v-if="project?.updated_at">Updated {{ formatRelativeDate(project.updated_at) }}</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api'
import GraphPanel from '../components/GraphPanel.vue'
import ChatPanel from '../components/ChatPanel.vue'
import UploadZone from '../components/UploadZone.vue'
import QuickNote from '../components/QuickNote.vue'

const route = useRoute()
const projectId = computed(() => route.params.id)

const project = ref(null)
const projects = ref([])
const graphData = ref(null)
const graphLoading = ref(false)
const viewMode = ref('split')
const showUpload = ref(false)
const showQuickNote = ref(false)
const sidebarOpen = ref(false)
const highlightNodes = ref([])
const highlightEdges = ref([])
const memoryStatus = ref(null)

const viewModes = [
  { key: 'graph', label: 'Graph' },
  { key: 'split', label: 'Split' },
  { key: 'chat', label: 'Chat' }
]

const fetchProject = async () => {
  try {
    const res = await api.get(`/api/projects/${projectId.value}`)
    project.value = res.project || res.data?.project || res
  } catch (error) {
    console.error('Failed to fetch project:', error)
  }
}

const fetchProjects = async () => {
  try {
    const res = await api.get('/api/projects')
    projects.value = res.data || res || []
  } catch (error) {
    console.error('Failed to fetch projects:', error)
  }
}

const fetchGraphData = async () => {
  graphLoading.value = true
  try {
    const res = await api.get(`/api/projects/${projectId.value}/graph`)
    graphData.value = res.graph || res.data?.graph || res
    if (project.value && graphData.value) {
      project.value = {
        ...project.value,
        node_count: graphData.value.nodes?.length || 0,
        edge_count: graphData.value.edges?.length || 0
      }
    }
  } catch (error) {
    console.error('Failed to fetch graph data:', error)
    graphData.value = null
  } finally {
    graphLoading.value = false
  }
}

const fetchMemoryStatus = async () => {
  try {
    const res = await api.get('/api/memory/status')
    memoryStatus.value = res.data || res
  } catch {
    // Silently fail — status bar just shows stale data
  }
}

const refreshGraph = () => {
  fetchGraphData()
  fetchProject()
}

const onUploaded = () => {
  showUpload.value = false
  refreshGraph()
}

const handleReferenceClick = (nodeUuid) => {
  highlightNodes.value = [nodeUuid]
  if (viewMode.value === 'chat') {
    viewMode.value = 'split'
  }
  setTimeout(() => {
    highlightNodes.value = []
  }, 3000)
}

const handleReferencesUpdated = (refs) => {
  highlightNodes.value = refs.nodes || []
  highlightEdges.value = refs.edges || []
  // Auto-clear highlights after 5 seconds
  setTimeout(() => {
    highlightNodes.value = []
    highlightEdges.value = []
  }, 5000)
}

const exportProject = async () => {
  try {
    const res = await api.get(`/api/projects/${projectId.value}/export`)
    const data = res.data || res
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${project.value?.name || 'project'}-export.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Failed to export project:', error)
  }
}

const formatRelativeDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    const now = new Date()
    const diffMs = now - d
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHrs = Math.floor(diffMins / 60)
    if (diffHrs < 24) return `${diffHrs}h ago`
    const diffDays = Math.floor(diffHrs / 24)
    return `${diffDays}d ago`
  } catch {
    return ''
  }
}

// Poll memory status every 15 seconds
let statusInterval = null

watch(projectId, () => {
  fetchProject()
  fetchGraphData()
  fetchMemoryStatus()
})

onMounted(() => {
  fetchProject()
  fetchProjects()
  fetchGraphData()
  fetchMemoryStatus()
  statusInterval = setInterval(fetchMemoryStatus, 15000)
})

onBeforeUnmount(() => {
  if (statusInterval) clearInterval(statusInterval)
})
</script>

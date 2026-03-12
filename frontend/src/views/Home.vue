<template>
  <div class="min-h-screen bg-gray-50">
    <!-- Header -->
    <header class="bg-white border-b border-gray-200 sticky top-0 z-30">
      <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
            <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <circle cx="12" cy="5" r="3" />
              <circle cx="5" cy="19" r="3" />
              <circle cx="19" cy="19" r="3" />
              <line x1="12" y1="8" x2="5" y2="16" />
              <line x1="12" y1="8" x2="19" y2="16" />
            </svg>
          </div>
          <h1 class="text-xl font-bold text-gray-900">Graphiti Studio</h1>
        </div>
        <div class="flex items-center gap-3">
          <router-link
            to="/settings"
            class="px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
          >
            Settings
          </router-link>
          <button
            @click="showNewDialog = true"
            class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors flex items-center gap-2"
          >
            <span class="text-lg leading-none">+</span>
            New Project
          </button>
        </div>
      </div>
    </header>

    <!-- Content -->
    <main class="max-w-7xl mx-auto px-6 py-8">
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="w-8 h-8 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin"></div>
      </div>

      <!-- Empty state -->
      <div v-else-if="projects.length === 0" class="text-center py-20">
        <div class="w-16 h-16 bg-gray-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path d="M12 4.5v15m7.5-7.5h-15" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </div>
        <h3 class="text-lg font-medium text-gray-900 mb-1">No projects yet</h3>
        <p class="text-gray-500 mb-6">Create your first knowledge graph project to get started.</p>
        <button
          @click="showNewDialog = true"
          class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
        >
          Create Project
        </button>
      </div>

      <!-- Project grid -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        <div
          v-for="project in projects"
          :key="project.id"
          class="bg-white rounded-xl border border-gray-200 hover:border-indigo-300 hover:shadow-md transition-all cursor-pointer group"
          @click="$router.push(`/project/${project.id}`)"
        >
          <div class="p-5">
            <div class="flex items-start justify-between mb-3">
              <h3 class="text-base font-semibold text-gray-900 group-hover:text-indigo-600 transition-colors truncate pr-2">
                {{ project.name }}
              </h3>
              <button
                @click.stop="confirmDelete(project)"
                class="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-500 transition-all rounded"
                title="Delete project"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" stroke-linecap="round" stroke-linejoin="round" />
                </svg>
              </button>
            </div>
            <p v-if="project.description" class="text-sm text-gray-500 mb-4 line-clamp-2">
              {{ project.description }}
            </p>
            <div class="flex items-center gap-4 text-xs text-gray-400">
              <span class="flex items-center gap-1">
                <span class="w-2 h-2 bg-indigo-400 rounded-full"></span>
                {{ project.node_count || 0 }} nodes
              </span>
              <span class="flex items-center gap-1">
                <span class="w-2 h-2 bg-emerald-400 rounded-full"></span>
                {{ project.edge_count || 0 }} edges
              </span>
              <span class="ml-auto">{{ formatDate(project.updated_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- New Project Dialog -->
    <div v-if="showNewDialog" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="showNewDialog = false">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 overflow-hidden">
        <div class="px-6 py-5 border-b border-gray-100">
          <h2 class="text-lg font-semibold text-gray-900">New Project</h2>
        </div>
        <form @submit.prevent="createProject" class="px-6 py-5 space-y-4">
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
            <input
              v-model="newProject.name"
              type="text"
              required
              placeholder="My Knowledge Graph"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            />
          </div>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
            <textarea
              v-model="newProject.description"
              rows="3"
              placeholder="What is this project about?"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-none"
            ></textarea>
          </div>
          <div class="flex justify-end gap-3 pt-2">
            <button
              type="button"
              @click="showNewDialog = false"
              class="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 rounded-lg hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              :disabled="creating"
              class="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50"
            >
              {{ creating ? 'Creating...' : 'Create' }}
            </button>
          </div>
        </form>
      </div>
    </div>

    <!-- Delete Confirmation Dialog -->
    <div v-if="deleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="deleteTarget = null">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 overflow-hidden">
        <div class="px-6 py-5">
          <h2 class="text-lg font-semibold text-gray-900 mb-2">Delete Project</h2>
          <p class="text-sm text-gray-500">
            Are you sure you want to delete <strong>{{ deleteTarget.name }}</strong>? This action cannot be undone.
          </p>
        </div>
        <div class="px-6 py-4 bg-gray-50 flex justify-end gap-3">
          <button
            @click="deleteTarget = null"
            class="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 rounded-lg hover:bg-gray-200 transition-colors"
          >
            Cancel
          </button>
          <button
            @click="deleteProject"
            :disabled="deleting"
            class="px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
          >
            {{ deleting ? 'Deleting...' : 'Delete' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'

const projects = ref([])
const loading = ref(true)
const showNewDialog = ref(false)
const creating = ref(false)
const deleteTarget = ref(null)
const deleting = ref(false)

const newProject = ref({
  name: '',
  description: ''
})

const fetchProjects = async () => {
  loading.value = true
  try {
    const res = await api.get('/api/projects')
    projects.value = res.projects || res.data?.projects || (Array.isArray(res) ? res : [])
  } catch (error) {
    console.error('Failed to fetch projects:', error)
    projects.value = []
  } finally {
    loading.value = false
  }
}

const createProject = async () => {
  if (!newProject.value.name.trim()) return
  creating.value = true
  try {
    await api.post('/api/projects', {
      name: newProject.value.name.trim(),
      description: newProject.value.description.trim()
    })
    showNewDialog.value = false
    newProject.value = { name: '', description: '' }
    await fetchProjects()
  } catch (error) {
    console.error('Failed to create project:', error)
    alert('Failed to create project. Please try again.')
  } finally {
    creating.value = false
  }
}

const confirmDelete = (project) => {
  deleteTarget.value = project
}

const deleteProject = async () => {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await api.delete(`/api/projects/${deleteTarget.value.id}`)
    deleteTarget.value = null
    await fetchProjects()
  } catch (error) {
    console.error('Failed to delete project:', error)
    alert('Failed to delete project. Please try again.')
  } finally {
    deleting.value = false
  }
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return dateStr
  }
}

onMounted(fetchProjects)
</script>

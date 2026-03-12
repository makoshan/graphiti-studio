import { ref, unref } from 'vue'

export function useChat(projectId) {
  const messages = ref([])
  const streaming = ref(false)
  const currentReferences = ref({ nodes: [], edges: [] })
  const currentThreadId = ref(null)
  const toolStatus = ref(null)

  async function send(text) {
    if (!text.trim() || streaming.value) return

    messages.value.push({
      role: 'user',
      content: text,
      timestamp: new Date().toISOString()
    })

    const assistantMsg = {
      role: 'assistant',
      content: '',
      timestamp: new Date().toISOString(),
      references: { nodes: [], edges: [] }
    }
    messages.value.push(assistantMsg)

    streaming.value = true
    toolStatus.value = null
    currentReferences.value = { nodes: [], edges: [] }

    try {
      const pid = unref(projectId)
      const response = await fetch(`/api/projects/${pid}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          thread_id: currentThreadId.value
        })
      })

      // Read thread_id from response header
      const headerThreadId = response.headers.get('X-Thread-Id')
      if (headerThreadId) {
        currentThreadId.value = headerThreadId
      }

      if (!response.ok) {
        throw new Error(`Chat request failed: ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // Parse SSE events (format: "event: <type>\ndata: <json>\n\n")
        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop() || ''

        for (const block of blocks) {
          if (!block.trim()) continue

          let eventType = ''
          const dataLines = []

          for (const line of block.split(/\r?\n/)) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              dataLines.push(line.slice(6))
            }
          }

          let eventData = null
          const dataStr = dataLines.join('\n').trim()
          if (dataStr && dataStr !== '[DONE]') {
            try {
              eventData = JSON.parse(dataStr)
            } catch {
              continue
            }
          }

          if (!eventData) continue

          switch (eventType) {
            case 'start':
              break

            case 'text_chunk':
              assistantMsg.content += eventData.text || ''
              messages.value = [...messages.value]
              break

            case 'tool_call':
              toolStatus.value = eventData.name
                ? `Searching: ${eventData.name}...`
                : 'Searching graph...'
              break

            case 'tool_result':
              toolStatus.value = null
              break

            case 'end':
              if (eventData.content) {
                assistantMsg.content = eventData.content
              }
              if (eventData.references) {
                assistantMsg.references = eventData.references
                currentReferences.value = eventData.references
              }
              messages.value = [...messages.value]
              break

            case 'error':
              assistantMsg.content += `\n\n[Error: ${eventData.message || 'Unknown error'}]`
              messages.value = [...messages.value]
              break
          }
        }
      }
    } catch (error) {
      console.error('Chat error:', error)
      assistantMsg.content += `\n\n[Error: ${error.message}]`
      messages.value = [...messages.value]
    } finally {
      streaming.value = false
      toolStatus.value = null
    }
  }

  function clearMessages() {
    messages.value = []
    currentThreadId.value = null
    currentReferences.value = { nodes: [], edges: [] }
  }

  return {
    messages,
    streaming,
    currentReferences,
    currentThreadId,
    toolStatus,
    send,
    clearMessages
  }
}

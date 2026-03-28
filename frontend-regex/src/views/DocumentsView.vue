<script setup>
import { ref, onMounted, computed } from 'vue'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const uploadDialog = ref(false)
const selectedDocument = ref(null)
const contentDialog = ref(false)
const isDragging = ref(false)
const uploadProgress = ref(0)
const selectedFile = ref(null)

const documentStatus = ref({})

const headers = [
  { title: 'Nom', key: 'filename', sortable: true },
  { title: 'Taille', key: 'size_bytes', sortable: true },
  { title: 'Statut', key: 'status', sortable: true },
  { title: 'Pages', key: 'pages', sortable: false },
  { title: 'Date', key: 'uploaded_at', sortable: true },
  { title: 'Actions', key: 'actions', sortable: false },
]

onMounted(() => {
  store.fetchDocuments()
})

async function handleFileSelect(event) {
  const file = event.target.files?.[0] || event.dataTransfer?.files?.[0]
  if (file) {
    selectedFile.value = file
    uploadDialog.value = true
  }
}

async function uploadFile() {
  if (!selectedFile.value) return

  try {
    const result = await store.uploadDocument(selectedFile.value)
    
    const interval = setInterval(async () => {
      const status = await store.getDocumentStatus(result.document_id)
      documentStatus.value[result.document_id] = status
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(interval)
        await store.fetchDocuments()
      }
    }, 2000)

    uploadDialog.value = false
    selectedFile.value = null
  } catch (e) {
    console.error('Upload failed:', e)
  }
}

async function viewContent(doc) {
  selectedDocument.value = doc
  await store.getDocumentContent(doc.document_id || doc.id)
  contentDialog.value = true
}

async function deleteDoc(doc) {
  if (confirm(`Supprimer "${doc.filename}" ?`)) {
    await store.deleteDocument(doc.document_id || doc.id)
  }
}

async function retryExtract(doc) {
  try {
    const id = doc.document_id || doc.id
    await store.retryExtract(id)
    const interval = setInterval(async () => {
      const status = await store.getDocumentStatus(id)
      documentStatus.value[id] = status
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(interval)
        await store.fetchDocuments()
      }
    }, 2000)
  } catch (e) {
    console.error('Retry failed:', e)
  }
}

async function retryIndex(doc) {
  try {
    const id = doc.document_id || doc.id
    await store.retryIndex(id)
    await store.fetchDocuments()
  } catch (e) {
    console.error('Reindex failed:', e)
  }
}

function formatSize(bytes) {
  if (!bytes) return '-'
  const kb = bytes / 1024
  if (kb < 1024) return `${kb.toFixed(1)} KB`
  return `${(kb / 1024).toFixed(1)} MB`
}

function getStatusColor(status) {
  const colors = {
    pending: 'warning',
    processing: 'info',
    completed: 'success',
    failed: 'error',
  }
  return colors[status] || 'grey'
}
</script>

<template>
  <div>
    <v-row class="mb-6">
      <v-col cols="12">
        <h1 class="text-h4 font-weight-bold">
          <v-icon icon="mdi-file-document" class="mr-2" />
          Documents
        </h1>
        <p class="text-body-1 text-medium-emphasis">
          Gestion des documents pour détection d'incohérences
        </p>
      </v-col>
    </v-row>

    <v-card
      class="upload-zone mb-6 pa-8"
      :class="{ dragover: isDragging }"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleFileSelect($event)"
      @click="$refs.fileInput.click()"
    >
      <input
        ref="fileInput"
        type="file"
        accept=".pdf,.jpg,.jpeg,.png"
        style="display: none"
        @change="handleFileSelect"
      />
      <div class="text-center">
        <v-icon icon="mdi-cloud-upload" size="64" color="primary" class="mb-4" />
        <h3 class="text-h6 mb-2">Glissez-déposez vos fichiers ici</h3>
        <p class="text-body-2 text-medium-emphasis">
          PDF, JPG, PNG acceptés (max 50MB PDF, 10MB images)
        </p>
      </div>
    </v-card>

    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon icon="mdi-format-list-bulleted" class="mr-2" />
        Documents ({{ store.documents.length }})
        <v-spacer />
        <v-btn
          icon="mdi-refresh"
          variant="text"
          @click="store.fetchDocuments()"
        />
      </v-card-title>

      <v-data-table
        :headers="headers"
        :items="store.documents"
        :loading="store.loading"
        hover
      >
        <template v-slot:item.filename="{ item }">
          <div class="d-flex align-center">
            <v-icon
              :icon="item.filename?.endsWith('.pdf') ? 'mdi-file-pdf-box' : 'mdi-file-image'"
              class="mr-2"
              :color="item.filename?.endsWith('.pdf') ? 'error' : 'info'"
            />
            {{ item.filename }}
          </div>
        </template>

        <template v-slot:item.size_bytes="{ item }">
          {{ formatSize(item.size_bytes) }}
        </template>

        <template v-slot:item.status="{ item }">
          <v-chip
            :color="getStatusColor(item.status)"
            size="small"
          >
            {{ item.status }}
          </v-chip>
        </template>

        <template v-slot:item.pages="{ item }">
          {{ item.total_pages || item.num_pages || '-' }}
        </template>

        <template v-slot:item.uploaded_at="{ item }">
          {{ item.uploaded_at ? new Date(item.uploaded_at).toLocaleDateString() : '-' }}
        </template>

        <template v-slot:item.actions="{ item }">
          <v-btn
            v-if="item.status === 'failed'"
            icon="mdi-refresh"
            size="small"
            variant="text"
            color="warning"
            title="Réessayer l'extraction"
            @click="retryExtract(item)"
          />
          <v-btn
            v-if="item.status === 'completed'"
            icon="mdi-database-refresh"
            size="small"
            variant="text"
            color="info"
            title="Relancer l'indexation"
            @click="retryIndex(item)"
          />
          <v-btn
            icon="mdi-eye"
            size="small"
            variant="text"
            :disabled="item.status !== 'completed'"
            @click="viewContent(item)"
          />
          <v-btn
            icon="mdi-delete"
            size="small"
            variant="text"
            color="error"
            @click="deleteDoc(item)"
          />
        </template>
      </v-data-table>
    </v-card>

    <v-dialog v-model="uploadDialog" max-width="500">
      <v-card>
        <v-card-title>Téléchargement</v-card-title>
        <v-card-text>
          <p class="mb-4">Fichier: {{ selectedFile?.name }}</p>
          <v-progress-linear
            v-model="uploadProgress"
            color="primary"
            striped
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="uploadDialog = false">Annuler</v-btn>
          <v-btn color="primary" @click="uploadFile">Télécharger</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="contentDialog" max-width="900">
      <v-card v-if="store.currentDocument">
        <v-card-title>
          <v-icon icon="mdi-file-document" class="mr-2" />
          {{ store.currentDocument.filename }}
        </v-card-title>
        <v-card-text>
          <v-tabs>
            <v-tab value="content">Contenu OCR</v-tab>
            <v-tab value="layout">Layout</v-tab>
          </v-tabs>
          <v-tabs-window>
            <v-tabs-window-item value="content">
              <div class="pa-4" style="max-height: 60vh; overflow-y: auto;">
                <pre class="text-body-2">{{ store.currentDocument.markdown }}</pre>
              </div>
            </v-tabs-window-item>
            <v-tabs-window-item value="layout">
              <div class="pa-4" style="max-height: 60vh; overflow-y: auto;">
                <pre class="text-body-2">{{ JSON.stringify(store.currentDocument.layout, null, 2) }}</pre>
              </div>
            </v-tabs-window-item>
          </v-tabs-window>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="contentDialog = false">Fermer</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

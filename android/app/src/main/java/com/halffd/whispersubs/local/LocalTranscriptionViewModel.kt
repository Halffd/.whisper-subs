package com.halffd.whispersubs.local

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LocalTranscriptionViewModel(application: Application) : AndroidViewModel(application) {

    data class UiState(
        val models: List<WhisperModel> = emptyList(),
        val downloadedModels: List<WhisperModel> = emptyList(),
        val selectedModel: WhisperModel? = null,
        val downloadProgress: Float = 0f,
        val isDownloading: Boolean = false,
        val error: String? = null,
    )

    private val _state = MutableStateFlow(UiState(models = ModelManager.AVAILABLE_MODELS))
    val state: StateFlow<UiState> = _state

    init {
        refreshDownloaded()
    }

    fun loadModels() {
        _state.value = _state.value.copy(models = ModelManager.AVAILABLE_MODELS)
        refreshDownloaded()
    }

    fun refreshDownloaded() {
        val downloaded = ModelManager.getDownloadedModels(getApplication())
        val current = _state.value
        val selected = current.selectedModel
            ?.takeIf { ModelManager.isModelDownloaded(getApplication(), it.id) }
            ?: downloaded.firstOrNull()
        _state.value = current.copy(downloadedModels = downloaded, selectedModel = selected)
    }

    fun selectModel(model: WhisperModel) {
        _state.value = _state.value.copy(selectedModel = model)
    }

    fun downloadModel(model: WhisperModel) {
        if (ModelManager.isModelDownloaded(getApplication(), model.id)) return

        _state.value = _state.value.copy(isDownloading = true, downloadProgress = 0f, error = null)

        viewModelScope.launch(Dispatchers.IO) {
            val success = ModelManager.downloadModel(getApplication(), model) { progress ->
                _state.value = _state.value.copy(downloadProgress = progress)
            }

            withContext(Dispatchers.Main) {
                if (success) {
                    _state.value = _state.value.copy(isDownloading = false, downloadProgress = 1f)
                    refreshDownloaded()
                    _state.value = _state.value.copy(selectedModel = model)
                } else {
                    _state.value = _state.value.copy(
                        isDownloading = false,
                        error = "Failed to download ${model.name}"
                    )
                }
            }
        }
    }

    fun deleteModel(model: WhisperModel) {
        val success = ModelManager.deleteModel(getApplication(), model.id)
        if (success) {
            refreshDownloaded()
        } else {
            _state.value = _state.value.copy(error = "Failed to delete ${model.name}")
        }
    }
}
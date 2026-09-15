package com.halffd.whispersubs.local

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.viewModelScope
import com.halffd.whispersubs.local.ModelManager.WhisperModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class LocalTranscriptionViewModel(application: Application) : AndroidViewModel(application) {

    private val _models = MutableLiveData<List<WhisperModel>>()
    val models: LiveData<List<WhisperModel>> = _models

    private val _downloadedModels = MutableLiveData<List<WhisperModel>>()
    val downloadedModels: LiveData<List<WhisperModel>> = _downloadedModels

    private val _selectedModel = MutableLiveData<WhisperModel?>()
    val selectedModel: LiveData<WhisperModel?> = _selectedModel

    private val _downloadProgress = MutableLiveData<Float>()
    val downloadProgress: LiveData<Float> = _downloadProgress

    private val _isDownloading = MutableLiveData<Boolean>()
    val isDownloading: LiveData<Boolean> = _isDownloading

    private val _error = MutableLiveData<String?>()
    val error: LiveData<String?> = _error

    init {
        loadModels()
    }

    fun loadModels() {
        _models.value = ModelManager.AVAILABLE_MODELS
        refreshDownloaded()
    }

    fun refreshDownloaded() {
        _downloadedModels.value = ModelManager.getDownloadedModels(getApplication())
        if (_selectedModel.value?.let { !ModelManager.isModelDownloaded(getApplication(), it.id) } == true) {
            _selectedModel.value = _downloadedModels.value?.firstOrNull()
        }
    }

    fun selectModel(model: WhisperModel) {
        _selectedModel.value = model
    }

    fun downloadModel(model: WhisperModel) {
        if (ModelManager.isModelDownloaded(getApplication(), model.id)) return

        _isDownloading.value = true
        _downloadProgress.value = 0f
        _error.value = null

        viewModelScope.launch(Dispatchers.IO) {
            val success = withContext(Dispatchers.IO) {
                ModelManager.downloadModel(getApplication(), model) { progress ->
                    _downloadProgress.postValue(progress)
                }
            }

            _isDownloading.postValue(false)
            if (success) {
                _downloadProgress.postValue(1f)
                refreshDownloaded()
                if (_selectedModel.value == null) _selectedModel.value = model
            } else {
                _error.postValue("Failed to download ${model.name}")
            }
        }
    }

    fun deleteModel(model: WhisperModel) {
        val success = ModelManager.deleteModel(getApplication(), model.id)
        if (success) {
            refreshDownloaded()
        } else {
            _error.value = "Failed to delete ${model.name}"
        }
    }
}
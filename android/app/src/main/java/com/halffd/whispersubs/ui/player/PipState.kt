package com.halffd.whispersubs.ui.player

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Whether the app is currently in picture-in-picture mode.
 * Updated by MainActivity.onPictureInPictureModeChanged.
 */
object PipState {
    var isInPip by mutableStateOf(false)
        internal set
}

package com.halffd.whispersubs.data

import android.content.Context
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    @Provides
    @Singleton
    fun provideServerConfig(@dagger.hilt.android.qualifiers.ApplicationContext context: Context): ServerConfig {
        return ServerConfig.getInstance(context)
    }

    @Provides
    @Singleton
    fun provideApiClient(serverConfig: ServerConfig): ApiClient {
        return ApiClient(serverConfig)
    }
}
import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.jacaranda.flavors',
  appName: 'Jacaranda Flavors',
  webDir: '../docs',
  server: {
    // In production, use the GitHub Pages URL
    url: 'https://alonsojc.github.io/jacaranda/',
    cleartext: true,
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: '#fdf9f7',
      androidSplashResourceName: 'splash',
      androidScaleType: 'CENTER_CROP',
      showSpinner: false,
      splashFullScreen: true,
      splashImmersive: true,
    },
    StatusBar: {
      style: 'LIGHT',
      backgroundColor: '#c4988a',
    },
    Keyboard: {
      resize: 'body',
      style: 'LIGHT',
    },
    LocalNotifications: {
      smallIcon: 'ic_stat_icon',
      iconColor: '#c4988a',
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
  android: {
    allowMixedContent: true,
    captureInput: true,
    webContentsDebuggingEnabled: false,
  },
  ios: {
    contentInset: 'automatic',
    allowsLinkPreview: false,
    scrollEnabled: true,
  },
};

export default config;

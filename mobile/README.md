# Jacaranda Flavors - App Móvil

Wrapper nativo usando [Capacitor](https://capacitorjs.com/) sobre la PWA existente.

## Requisitos

- Node.js 18+
- Android Studio (para Android)
- Xcode 15+ (para iOS, solo macOS)

## Setup

```bash
cd mobile
npm install
npx cap add android   # o npx cap add ios
npx cap sync
```

## Desarrollo

```bash
# Abrir en Android Studio
npx cap open android

# Abrir en Xcode
npx cap open ios

# Ejecutar en dispositivo/emulador
npx cap run android
npx cap run ios
```

## Arquitectura

La app móvil carga la PWA existente desde `../docs/index.html` (GitHub Pages).
Capacitor provee acceso a APIs nativas:

- **Camera**: Para escanear tickets/OCR
- **Haptics**: Feedback táctil en POS
- **Local Notifications**: Alertas de producción y pedidos
- **Share**: Compartir tickets y reportes
- **Status Bar**: Integración con tema Jacaranda

## Publicación

### Android (Google Play)
```bash
npx cap sync android
cd android && ./gradlew assembleRelease
```

### iOS (App Store)
```bash
npx cap sync ios
# Abrir en Xcode y archivar para distribución
npx cap open ios
```

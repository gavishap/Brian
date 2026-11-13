// Custom entry point. The background notification task must be defined at module scope before the
// app renders, so the OS can run it in a headless JS context (Android action buttons, deliveries).
import './src/notifications/task';
import 'expo-router/entry';

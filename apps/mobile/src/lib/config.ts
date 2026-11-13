// EXPO_PUBLIC_* variables are inlined at build time (see .env.example).
function required(name: string, value: string | undefined): string {
  if (!value) {
    // Fail loudly in development; a release build without config is a packaging mistake.
    console.warn(`Missing ${name}; copy apps/mobile/.env.example to .env`);
    return '';
  }
  return value.replace(/\/+$/, '');
}

export const config = {
  apiUrl: required('EXPO_PUBLIC_API_URL', process.env.EXPO_PUBLIC_API_URL),
  supabaseUrl: required('EXPO_PUBLIC_SUPABASE_URL', process.env.EXPO_PUBLIC_SUPABASE_URL),
  supabaseAnonKey: process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? '',
};

import { jest } from '@jest/globals';

// Native modules have no implementation under Jest; use the library-provided mocks.
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

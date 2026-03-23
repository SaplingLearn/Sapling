const nextJest = require('next/jest');

const createJestConfig = nextJest({ dir: './' });

module.exports = createJestConfig({
  testEnvironment: 'jest-environment-jsdom',
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '^remark-math$': '<rootDir>/src/__mocks__/remarkMath.js',
    '^rehype-katex$': '<rootDir>/src/__mocks__/rehypeKatex.js',
    'katex/dist/katex.min.css': '<rootDir>/src/__mocks__/styleMock.js',
  },
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
});

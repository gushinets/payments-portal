type RuntimeEnvironment = Record<string, string | undefined>;

declare const runtimeEnv: {
  loadRuntimeEnv(
    repositoryRoot: string,
    targetEnv?: RuntimeEnvironment
  ): Record<string, string>;
  readRuntimeEnv(repositoryRoot: string): Record<string, string>;
};

export = runtimeEnv;

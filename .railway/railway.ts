import { defineRailway, preserve, project, service } from "railway/iac";

export const partial = "jacaranda-uber-sandbox-receiver";

export default defineRailway((ctx) => {
  if (
    ctx.projectId !== "dbcece93-ecb8-459b-9d95-6900a265bd6e" ||
    ctx.environmentId !== "aa6e8019-6389-4e4e-8689-63f8bfcb626d" ||
    ctx.environment !== "uber-sandbox"
  ) {
    throw new Error("This configuration must never target production.");
  }

  const receiver = service("uber-sandbox-webhook", {
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    start: "python -m app.uber_sandbox_runtime",
    healthcheck: "/health",
    healthcheckTimeout: 120,
    replicas: { "us-east4-eqdc4a": 1 },
    env: {
      DATABASE_URL: "${{uber-sandbox-db.DATABASE_URL}}",
      DEBUG: "false",
      JACARANDA_RUNTIME: "uber-sandbox",
      JACARANDA_SANDBOX_DATABASE_HOST: "${{uber-sandbox-db.RAILWAY_PRIVATE_DOMAIN}}",
      UBER_EATS_SANDBOX_ACTIONS_ENABLED: "false",
      UBER_EATS_SANDBOX_CLIENT_ID: "I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL",
      UBER_EATS_SANDBOX_ENABLED: "true",
      UBER_EATS_SANDBOX_STORE_ID: "b412bb20-cf36-4ada-ba77-fdda96ce8a9e",
      UBER_EATS_SANDBOX_WEBHOOK_ENABLED: "true",
      UBER_EATS_SANDBOX_WEBHOOK_SECRET: preserve(),
    },
    deploy: {
      limitOverride: { containers: { cpu: 0.1, memoryBytes: 250000000 } },
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 3,
      sleepApplication: false,
    },
  });

  return project("Jacaranda", { resources: [receiver] });
});

import { defineRailway, github, project, service, volume } from "railway/iac";

export const partial = "web";

export default defineRailway((ctx) => {
  if (ctx.projectName !== "Jacaranda" || ctx.environment !== "production") {
    throw new Error("Esta configuración corresponde al entorno production de Jacaranda.");
  }

  const region = "us-east4-eqdc4a";
  const webData = volume("web-volume", {
    region,
    sizeMB: 500,
    allowOnlineResize: true,
    alerts: { usage: { "80": {}, "95": {}, "100": {} } },
  });

  const web = service("web", {
    source: github("Alonsojc/jacaranda", { branch: "main", checkSuites: false }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: {
      startCommand: "python start.py",
      healthcheckPath: "/ready",
      healthcheckTimeout: 300,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 10,
    },
    replicas: { [region]: 1 },
    volumeMounts: { "/data": webData },
  });

  return project("Jacaranda", {
    variables: { managed: false },
    resources: [web, webData],
  });
});

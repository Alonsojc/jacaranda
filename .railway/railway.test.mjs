import assert from "node:assert/strict";
import test from "node:test";

import configure, { partial } from "./railway.ts";

test("producción conserva arranque, salud, reintentos y el volumen web", () => {
  const config = configure({ projectName: "Jacaranda", environment: "production" });
  assert.equal(partial, "web");
  assert.deepEqual(config.variables, { managed: false });
  assert.deepEqual(config.resources.map(resource => resource.address).sort(), [
    "service.web", "volume.web-volume",
  ]);
  const web = config.resources.find(resource => resource.address === "service.web");
  assert.deepEqual(web.build, { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" });
  assert.equal(web.deploy.startCommand, "python start.py");
  assert.equal(web.deploy.healthcheckPath, "/ready");
  assert.equal(web.deploy.healthcheckTimeout, 300);
  assert.equal(web.deploy.restartPolicyType, "ON_FAILURE");
  assert.equal(web.deploy.restartPolicyMaxRetries, 10);
  const data = web.volumeAttachments["web-volume"];
  assert.equal(data.mountPath, "/data");
  assert.equal(data.volume, "volume.web-volume");
  assert.equal(data.volumeConfig.region, "us-east4-eqdc4a");
});

test("la configuración de producción requiere su propio proyecto y entorno", () => {
  for (const [projectName, environment] of [["Jacaranda", "uber-sandbox"], ["Otro", "production"]]) {
    assert.throws(() => configure({ projectName, environment }), /production de Jacaranda/);
  }
});

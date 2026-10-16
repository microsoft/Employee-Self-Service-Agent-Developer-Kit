async (page, options = {}) => {
  const capture = options.capture !== false;
  const applicationUrl =
    typeof options.applicationUrl === "string"
      ? options.applicationUrl.trim()
      : "";
  if (!applicationUrl.includes("ManagedAppMenuBlade/~/Overview/")) {
    return {
      ok: false,
      failedAt: "missing-application-url",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }
  const expectedUrl = applicationUrl.replace(
    "ManagedAppMenuBlade/~/Overview/",
    "ManagedAppMenuBlade/~/SignOn/",
  );
  if (page.url() !== expectedUrl) {
    try {
      await page.goto(expectedUrl);
      await page.waitForURL(expectedUrl, { timeout: 10000 });
      await page.locator(".fxs-splashscreen").waitFor({
        state: "hidden",
        timeout: 15000,
      });
    } catch {
      return {
        ok: false,
        failedAt: "navigate-saml-sign-on",
        url: page.url(),
        error: "Initial direct navigation attempt failed",
      };
    }
  }
  if (page.url() !== expectedUrl) {
    return {
      ok: false,
      failedAt: "verify-saml-sign-on",
      url: page.url(),
      error: "Initial direct navigation attempt failed",
    };
  }

  const heading = page.getByText("SAML Certificates", { exact: true });
  try {
    await heading.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "locate-certificate-card",
      url: page.url(),
      matchCount: await heading.count(),
      error: error.message,
    };
  }

  const card = heading.locator(
    "xpath=ancestor::*[self::div or self::section][3]",
  );
  const certificateLabel = card.getByText("Certificate (Base64)", {
    exact: true,
  });
  if ((await certificateLabel.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-base64-certificate-label",
      url: page.url(),
      matchCount: await certificateLabel.count(),
    };
  }
  const certificateRow = certificateLabel.locator(
    "xpath=ancestor::*[contains(@class, 'ext-saml-row')][1]",
  );
  if ((await certificateRow.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-base64-certificate-row",
      url: page.url(),
      matchCount: await certificateRow.count(),
    };
  }
  const target = certificateRow.getByRole("link", {
    name: "Download",
    exact: true,
  });
  if ((await target.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-base64-certificate-download",
      url: page.url(),
      matchCount: await target.count(),
    };
  }
  try {
    await target.waitFor({ state: "visible", timeout: 10000 });
  } catch (error) {
    return {
      ok: false,
      failedAt: "wait-for-base64-certificate-download",
      url: page.url(),
      error: error.message,
    };
  }

  await target.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await target.boundingBox();
  if (!box) {
    return {
      ok: false,
      failedAt: "measure-active-certificate",
      url: page.url(),
    };
  }
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const center = box.y + box.height / 2;
  const result = {
    ok: true,
    targets: [
      {
        label: "Certificate (Base64): Download",
        positionRatio:
          Math.round(
            Math.min(Math.max(center / viewport.height, 0.05), 0.95) * 10000,
          ) / 10000,
        centered:
          Math.abs(center - viewport.height / 2) <=
          Math.max(24, box.height / 2),
      },
    ],
  };
  if (capture) {
    result.value = "The Certificate (Base64) download link is visible.";
  }
  return result;
};

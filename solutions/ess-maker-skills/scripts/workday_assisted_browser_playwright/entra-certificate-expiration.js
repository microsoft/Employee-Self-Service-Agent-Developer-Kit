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

  const heading = page.getByText("Token signing certificate", {
    exact: true,
  });
  const headingCount = await heading.count();
  if (headingCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-token-signing-certificate",
      url: page.url(),
      matchCount: headingCount,
    };
  }

  const section = heading.locator(
    "xpath=ancestor::*[contains(@class, 'ext-saml-sub-section-content')][1]",
  );
  const label = section.getByText("Expiration", { exact: true });
  const labelCount = await label.count();
  if (labelCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-expiration-label",
      url: page.url(),
      matchCount: labelCount,
    };
  }

  let expiration = null;
  let target = label;
  if (capture) {
    const row = label.locator(
      "xpath=ancestor::*[contains(@class, 'ext-saml-row')][1]",
    );
    const lines = (await row.innerText())
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (lines.length !== 2 || lines[0] !== "Expiration") {
      return {
        ok: false,
        failedAt: "read-expiration",
        url: page.url(),
      };
    }
    expiration = lines[1];
    target = row.getByText(expiration, { exact: true });
    const valueCount = await target.count();
    if (valueCount !== 1) {
      return {
        ok: false,
        failedAt: "locate-expiration-value",
        url,
        matchCount: valueCount,
      };
    }
  }

  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) {
    return {
      ok: false,
      failedAt: "measure-expiration",
      url,
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
        label: "Expiration under Token signing certificate",
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
    result.value = expiration;
  }
  return result;
};

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

  const signingOption = page.getByText("Sign SAML response and assertion", {
    exact: true,
  });
  let signingOptionCount = await signingOption.count();
  if (signingOptionCount === 0) {
    const edit = page.getByRole("button", {
      name: "Edit SAML signing certificate",
      exact: true,
    });
    const editCount = await edit.count();
    if (editCount !== 1) {
      return {
        ok: false,
        failedAt: "locate-edit-control",
        url: page.url(),
        matchCount: editCount,
      };
    }
    try {
      await edit.scrollIntoViewIfNeeded();
      await edit.click();
      await page.waitForTimeout(700);
    } catch (error) {
      return {
        ok: false,
        failedAt: "open-signing-editor",
        url: page.url(),
        error: error.message,
      };
    }
    signingOptionCount = await signingOption.count();
  }
  if (signingOptionCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-signing-option",
      url: page.url(),
      matchCount: signingOptionCount,
    };
  }

  const certificateHeading = page.getByText("SAML Certificates", {
    exact: true,
  });
  if ((await certificateHeading.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-certificate-card",
      url: page.url(),
      matchCount: await certificateHeading.count(),
    };
  }
  const certificateCard = certificateHeading.locator(
    "xpath=ancestor::*[self::div or self::section][3]",
  );
  const expirationLabel = certificateCard.getByText("Expiration", {
    exact: true,
  });
  if ((await expirationLabel.count()) !== 1) {
    return {
      ok: false,
      failedAt: "locate-expiration-label",
      url: page.url(),
      matchCount: await expirationLabel.count(),
    };
  }

  let expiration = null;
  let expirationTarget = expirationLabel;
  if (capture) {
    const expirationRow = expirationLabel.locator(
      "xpath=ancestor::*[contains(@class, 'ext-saml-row')][1]",
    );
    const lines = (await expirationRow.innerText())
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
    expirationTarget = expirationRow.getByText(expiration, {
      exact: true,
    });
    if ((await expirationTarget.count()) !== 1) {
      return {
        ok: false,
        failedAt: "locate-expiration-value",
        url: page.url(),
        matchCount: await expirationTarget.count(),
      };
    }
  }

  await signingOption.scrollIntoViewIfNeeded();
  await expirationTarget.scrollIntoViewIfNeeded();
  const signingOptionBox = await signingOption.boundingBox();
  if (!signingOptionBox) {
    return {
      ok: false,
      failedAt: "measure-signing-option",
      url: page.url(),
    };
  }
  const expirationBox = await expirationTarget.boundingBox();
  if (!expirationBox) {
    return {
      ok: false,
      failedAt: "measure-expiration",
      url: page.url(),
    };
  }
  const viewport = await page.evaluate(() => ({
    width: innerWidth,
    height: innerHeight,
  }));
  const signingOptionCenter =
    signingOptionBox.y + signingOptionBox.height / 2;
  const expirationCenter =
    expirationBox.y + expirationBox.height / 2;
  const result = {
    ok: true,
    targets: [
      {
        label: "SAML signing option",
        positionRatio:
          Math.round(
            Math.min(
              Math.max(signingOptionCenter / viewport.height, 0.05),
              0.95,
            ) * 10000,
          ) / 10000,
        centered:
          Math.abs(signingOptionCenter - viewport.height / 2) <=
          Math.max(24, signingOptionBox.height / 2),
      },
      {
        label: "Active certificate expiration",
        positionRatio:
          Math.round(
            Math.min(
              Math.max(expirationCenter / viewport.height, 0.05),
              0.95,
            ) * 10000,
          ) / 10000,
        centered:
          Math.abs(expirationCenter - viewport.height / 2) <=
          Math.max(24, expirationBox.height / 2),
      },
    ],
  };
  if (capture) {
    result.values = {
      "SAML signing": "Sign SAML response and assertion",
      "Certificate expiration date (active certificate row)": expiration,
    };
  }
  return result;
};

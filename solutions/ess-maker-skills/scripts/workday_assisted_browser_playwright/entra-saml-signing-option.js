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

  const signingPanel = page.getByRole("complementary", {
    name: "SAML Signing Certificate",
    exact: true,
  });
  let signingPanelCount = await signingPanel.count();
  let signingPanelVisible =
    signingPanelCount === 1 && (await signingPanel.isVisible());
  if (!signingPanelVisible) {
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
      await signingPanel.waitFor({
        state: "visible",
        timeout: 10000,
      });
    } catch (error) {
      return {
        ok: false,
        failedAt: "open-signing-editor",
        url: page.url(),
        error: error.message,
      };
    }
    signingPanelCount = await signingPanel.count();
    signingPanelVisible =
      signingPanelCount === 1 && (await signingPanel.isVisible());
  }
  if (!signingPanelVisible) {
    return {
      ok: false,
      failedAt: "locate-signing-panel",
      url: page.url(),
      matchCount: signingPanelCount,
    };
  }

  const signingOption = signingPanel.getByText(
    "Sign SAML response and assertion",
    {
      exact: true,
    },
  );
  const signingOptionCount = await signingOption.count();
  if (signingOptionCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-signing-option",
      url: page.url(),
      matchCount: signingOptionCount,
    };
  }

  const expirationHeader = signingPanel.getByText("Expiration Date", {
    exact: true,
  });
  const expirationHeaderCount = await expirationHeader.count();
  if (expirationHeaderCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-expiration-header",
      url: page.url(),
      matchCount: expirationHeaderCount,
    };
  }

  const thumbprintHeader = signingPanel.getByText("Thumbprint", {
    exact: true,
  });
  const thumbprintHeaderCount = await thumbprintHeader.count();
  if (thumbprintHeaderCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-thumbprint-header",
      url: page.url(),
      matchCount: thumbprintHeaderCount,
    };
  }

  const headerRow = thumbprintHeader.locator(
    "xpath=ancestor::*[@role='row'][1]",
  );
  const headerLines = (await headerRow.innerText())
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (
    headerLines.length < 3 ||
    headerLines[0] !== "Status" ||
    headerLines[1] !== "Expiration Date" ||
    headerLines[2] !== "Thumbprint"
  ) {
    return {
      ok: false,
      failedAt: "verify-certificate-columns",
      url: page.url(),
    };
  }

  const activeCell = signingPanel.getByRole("gridcell", {
    name: "Active",
    exact: true,
  });
  const activeCellCount = await activeCell.count();
  if (activeCellCount !== 1) {
    return {
      ok: false,
      failedAt: "locate-active-certificate-row",
      url: page.url(),
      matchCount: activeCellCount,
    };
  }
  const activeRow = activeCell.locator(
    "xpath=ancestor::*[@role='row'][1]",
  );
  const activeCells = activeRow.getByRole("gridcell");
  const activeCellValueCount = await activeCells.count();
  if (activeCellValueCount < 3) {
    return {
      ok: false,
      failedAt: "locate-active-certificate-values",
      url: page.url(),
      matchCount: activeCellValueCount,
    };
  }

  const expirationTarget = activeCells.nth(1);
  const thumbprintTarget = activeCells.nth(2);
  let expiration = null;
  let thumbprint = null;
  if (capture) {
    expiration = (await expirationTarget.innerText()).trim();
    if (!expiration) {
      return {
        ok: false,
        failedAt: "read-expiration",
        url: page.url(),
      };
    }
    thumbprint = (await thumbprintTarget.innerText()).trim();
    if (!thumbprint) {
      return {
        ok: false,
        failedAt: "read-thumbprint",
        url: page.url(),
      };
    }
  }

  await signingOption.scrollIntoViewIfNeeded();
  await thumbprintTarget.scrollIntoViewIfNeeded();
  await expirationTarget.scrollIntoViewIfNeeded();
  const signingOptionBox = await signingOption.boundingBox();
  if (!signingOptionBox) {
    return {
      ok: false,
      failedAt: "measure-signing-option",
      url: page.url(),
    };
  }
  const thumbprintBox = await thumbprintTarget.boundingBox();
  if (!thumbprintBox) {
    return {
      ok: false,
      failedAt: "measure-thumbprint",
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
  const thumbprintCenter =
    thumbprintBox.y + thumbprintBox.height / 2;
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
        label: "Active certificate thumbprint",
        positionRatio:
          Math.round(
            Math.min(
              Math.max(thumbprintCenter / viewport.height, 0.05),
              0.95,
            ) * 10000,
          ) / 10000,
        centered:
          Math.abs(thumbprintCenter - viewport.height / 2) <=
          Math.max(24, thumbprintBox.height / 2),
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
      "Certificate thumbprint (active certificate row)": thumbprint,
      "Certificate expiration date (active certificate row)": expiration,
    };
  }
  return result;
};

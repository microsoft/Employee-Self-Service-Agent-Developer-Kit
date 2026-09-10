using System.Text.Json;
using Microsoft.Agents.ObjectModel;
using Microsoft.Agents.ObjectModel.Yaml;

const int MaxErrorLength = 2000;
var outputOptions = new JsonSerializerOptions(JsonSerializerDefaults.Web);
var objectModelOptions = ElementSerializer.CreateOptions(indent: false);

static string BoundedMessage(Exception error)
{
    var message = string.IsNullOrWhiteSpace(error.Message)
        ? error.GetType().Name
        : error.Message;
    return message.Length <= MaxErrorLength
        ? message
        : message[..MaxErrorLength];
}

object Error(Exception error) => new
{
    code = "object-model-conversion-failed",
    type = error.GetType().Name,
    message = BoundedMessage(error),
};

try
{
    using var request = JsonDocument.Parse(await Console.In.ReadToEndAsync());
    var root = request.RootElement;
    if (
        !root.TryGetProperty("operation", out var operation)
        || operation.ValueKind != JsonValueKind.String
        || operation.GetString() != "object-model-to-yaml"
    )
    {
        throw new InvalidDataException(
            "operation must be object-model-to-yaml."
        );
    }
    if (
        !root.TryGetProperty("items", out var items)
        || items.ValueKind != JsonValueKind.Array
    )
    {
        throw new InvalidDataException("items must be an array.");
    }

    var results = new List<object>();
    foreach (var item in items.EnumerateArray())
    {
        var key = item.TryGetProperty("key", out var keyElement)
            && keyElement.ValueKind == JsonValueKind.String
                ? keyElement.GetString()
                : null;
        if (string.IsNullOrWhiteSpace(key))
        {
            throw new InvalidDataException(
                "Each item key must be a non-empty string."
            );
        }

        try
        {
            if (
                !item.TryGetProperty("objectModel", out var objectModel)
                || objectModel.ValueKind != JsonValueKind.Object
            )
            {
                throw new InvalidDataException(
                    "objectModel must be an object."
                );
            }
            var element = JsonSerializer.Deserialize<BotElement>(
                objectModel.GetRawText(),
                objectModelOptions
            ) ?? throw new InvalidDataException(
                "The Object Model JSON did not contain a BotElement."
            );
            if (element is not DialogBase)
            {
                throw new InvalidDataException(
                    $"Expected a dialog but received {element.GetType().Name}."
                );
            }
            results.Add(new
            {
                key,
                success = true,
                elementType = element.GetType().Name,
                yaml = YamlSerializer.Serialize(element),
            });
        }
        catch (Exception error)
        {
            results.Add(new
            {
                key,
                success = false,
                error = Error(error),
            });
        }
    }

    Console.Write(JsonSerializer.Serialize(
        new { success = true, results },
        outputOptions
    ));
    return 0;
}
catch (Exception error)
{
    Console.Write(JsonSerializer.Serialize(
        new { success = false, error = Error(error) },
        outputOptions
    ));
    return 1;
}

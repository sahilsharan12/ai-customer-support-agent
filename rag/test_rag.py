
from rag.retriever import retrieve_policy


def get_policy_context(query: str):

    results = retrieve_policy(query, top_k=3)

    if not results:
        return "No relevant policy information was found."

    context = []

    for index, result in enumerate(results, start=1):

        context.append(
            f"""
Policy Reference {index}
Source: {result['source']}
Policy Type: {result['policy_type']}

Content:
{result['content']}
"""
        )

    return "\n".join(context)


if __name__ == "__main__":

    query = (
        "I received a damaged product. "
        "Can I request a return and refund?"
    )

    print("=" * 60)
    print("RAG POLICY CONTEXT TEST")
    print("=" * 60)

    print("\nCUSTOMER QUERY:")
    print(query)

    context = get_policy_context(query)

    print("\nRETRIEVED CONTEXT:")
    print("=" * 60)
    print(context)
